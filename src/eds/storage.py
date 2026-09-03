"""Accès aux fichiers : un protocole, deux implémentations, une seule chaîne de traitement.

Le pipeline lit un dépôt et écrit un lake. Sur un poste, ce sont deux dossiers ;
sur Azure, deux conteneurs de stockage objet. Le reste du code ne doit pas avoir
à le savoir — d'où ce protocole.

Trois responsabilités, et pas une de plus :

* **ouvrir un flux** en lecture et en écriture. La pseudonymisation reste ainsi
  un traitement ligne à ligne, à mémoire constante, **de la source vers le lake** :
  l'identité en clair ne devient jamais un fichier intermédiaire. C'est ce qui
  permet de continuer à écrire qu'elle ne quitte pas le dépôt du CHU.
* **calculer une empreinte** du fichier source, clé d'idempotence de l'ingestion.
* **dire au moteur comment lire le lake**. `LocalStorage` rend un `file()`,
  `AzureBlobStorage` un `azureBlobStorage(...)`. Les scripts de chargement ne
  contiennent qu'un `FROM {lake_source}` : il n'existe **pas** deux versions du
  SQL de bronze, une par cible.

Ce que le protocole ne fait pas : transformer. Aucune règle métier ici.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol

from eds.config import Config
from eds.logging_setup import get_logger

log = get_logger(__name__)

DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CHUNK_SIZE = 1024 * 1024

# Au-delà de ce seuil, un fichier en cours d'écriture vers le stockage objet
# déborde sur un fichier temporaire au lieu de gonfler la mémoire. Ce qui déborde
# est du contenu **déjà pseudonymisé** : le lake, jamais la source.
_SPOOL_MAX = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SourceFile:
    """Un fichier déposé par le CHU, pour un domaine et un jour donnés.

    Volontairement sans chemin : c'est le `Storage` qui sait où il se trouve et
    comment l'ouvrir. Le même triplet désigne le fichier dans le dépôt et sa
    copie pseudonymisée dans le lake.
    """

    domain: str
    ingest_date: str
    relative_name: str

    @property
    def label(self) -> str:
        return f"{self.domain}/{self.ingest_date}/{self.relative_name}"

    @property
    def key(self) -> str:
        """Chemin relatif du fichier, identique dans les deux zones."""
        return f"{self.domain}/{self.ingest_date}/{self.relative_name}"


class StorageError(RuntimeError):
    """Zone de stockage inaccessible ou mal configurée."""


# ── Les deux façons de dire au moteur où lire ───────────────────────────────
# Fonctions pures, placées côte à côte : c'est ici, et nulle part ailleurs, que
# se lit la différence entre les deux cibles. Elles se testent sans entrepôt et
# sans compte cloud.


def file_table_function(source: SourceFile, fmt: str, structure: str | None) -> str:
    """Lecture d'un fichier du lake monté sous `user_files/` — cible locale.

    Signature positionnelle : (chemin, format, structure). Le chemin est relatif
    à `user_files`, jamais absolu côté hôte.
    """
    arguments = [_litteral(f"lake/{source.key}"), _litteral(fmt)]
    if structure:
        arguments.append(_litteral(structure))
    return f"file({', '.join(arguments)})"


def azure_table_function(
    source: SourceFile, fmt: str, structure: str | None, collection: str = "lake"
) -> str:
    """Lecture d'un blob du lake — cible Azure, par collection nommée.

    La collection est déclarée dans la configuration du serveur et porte l'URL
    SAS. La requête ne contient donc aucun secret : ni dans le SQL envoyé, ni
    dans `system.query_log`, ni dans les journaux du pipeline.

    ⚠ La forme positionnelle serait un piège :
    `azureBlobStorage(url, conteneur, chemin, format, structure)` fait lire le
    cinquième argument comme une **compression**, et la structure est alors
    inférée en silence — le typage explicite de bronze disparaîtrait sans erreur.
    """
    arguments = [collection, f"blob_path = {_litteral(source.key)}", f"format = {_litteral(fmt)}"]
    if structure:
        arguments.append(f"structure = {_litteral(structure)}")
    return f"azureBlobStorage({', '.join(arguments)})"


class Storage(Protocol):
    """Une zone de stockage : dépôt du CHU ou lake."""

    label: str

    def days(self, domain: str) -> list[str]:
        """Jours déposés pour un domaine, triés. Liste vide si le domaine est absent."""

    def list_files(self, domain: str, day: str) -> list[str]:
        """Fichiers réellement présents pour un domaine et un jour, triés.

        Sert aux domaines dont le contenu d'un jour n'est pas connu d'avance — les
        nomenclatures, dont le CHU ne dépose que celles qui changent. Un fichier
        présent mais non reconnu doit pouvoir être signalé, pas ignoré en silence.
        """

    def exists(self, source: SourceFile) -> bool: ...

    def open_read(self, source: SourceFile) -> IO[bytes]: ...

    def open_write(self, source: SourceFile) -> IO[bytes]:
        """Ouvre une écriture **atomique** : rien n'est publié avant la fermeture.

        Un incident en cours d'écriture laisse la zone dans son état précédent,
        jamais avec un fichier tronqué qui serait chargé sans que rien ne le signale.
        """

    def fingerprint(self, source: SourceFile) -> str:
        """SHA-256 du contenu, lu en flux."""

    def table_function(self, source: SourceFile, fmt: str, structure: str | None) -> str:
        """Expression SQL par laquelle ClickHouse lit ce fichier lui-même."""


# ── Zone locale : deux dossiers ─────────────────────────────────────────────
class LocalStorage:
    """Un dossier de l'hôte. Le lake est monté en lecture seule dans ClickHouse."""

    def __init__(self, root: Path, label: str) -> None:
        self.root = root
        self.label = label

    def _path(self, source: SourceFile) -> Path:
        return self.root / source.domain / source.ingest_date / source.relative_name

    def days(self, domain: str) -> list[str]:
        directory = self.root / domain
        if not directory.is_dir():
            return []
        jours = []
        for entry in sorted(directory.iterdir()):
            if not entry.is_dir():
                continue
            if not DAY_PATTERN.match(entry.name):
                log.warning("Dossier ignoré (nom de jour invalide) : %s", entry)
                continue
            jours.append(entry.name)
        return jours

    def list_files(self, domain: str, day: str) -> list[str]:
        directory = self.root / domain / day
        if not directory.is_dir():
            return []
        # Les fichiers cachés (`.DS_Store` sur macOS) ne sont jamais un dépôt.
        return sorted(
            entry.name
            for entry in directory.iterdir()
            if entry.is_file() and not entry.name.startswith(".")
        )

    def exists(self, source: SourceFile) -> bool:
        return self._path(source).is_file()

    def open_read(self, source: SourceFile) -> IO[bytes]:
        return self._path(source).open("rb")

    @contextmanager
    def open_write(self, source: SourceFile) -> Iterator[IO[bytes]]:
        """Écrit dans un fichier temporaire puis renomme : jamais de fichier partiel."""
        cible = self._path(source)
        cible.parent.mkdir(parents=True, exist_ok=True)
        tmp = cible.with_suffix(cible.suffix + ".tmp")
        try:
            with tmp.open("wb") as handle:
                yield handle
            os.replace(tmp, cible)
        finally:
            tmp.unlink(missing_ok=True)

    def fingerprint(self, source: SourceFile) -> str:
        return _sha256(self.open_read(source))

    def table_function(self, source: SourceFile, fmt: str, structure: str | None) -> str:
        return file_table_function(source, fmt, structure)

    def read_text(self, source: SourceFile) -> str:
        """Confort de lecture — tests et diagnostic, jamais le pipeline."""
        with self.open_read(source) as handle:
            return handle.read().decode("utf-8")


# ── Zone Azure : deux conteneurs d'un compte de blobs (sans espace de noms hiérarchique) ──
class AzureBlobStorage:
    """Un conteneur de stockage objet, joint par identité gérée.

    Authentification : `DefaultAzureCredential`. Dans le job Container Apps, c'est
    l'identité gérée assignée ; sur un poste, la session `az login`. Aucune clé de
    compte n'est manipulée par le pipeline.

    ⚠ ClickHouse, lui, ne peut pas utiliser cette identité : sans identifiants
    explicites, sa version 26.3 tente `WorkloadIdentityCredential`, qui n'existe que
    dans Kubernetes. Le moteur lit donc le lake par un jeton SAS de conteneur, en
    lecture seule et daté, déposé dans sa configuration au démarrage de la VM. La
    collection nommée `lake` en porte l'URL — le secret n'entre ni dans le SQL, ni
    dans `system.query_log`.
    """

    def __init__(self, account: str, container: str, label: str) -> None:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import ContainerClient
        except ImportError as exc:  # pragma: no cover - dépend de l'extra `azure`
            raise StorageError(
                "Le stockage Azure exige l'extra correspondant : uv sync --extra azure"
            ) from exc

        self.account = account
        self.container = container
        self.label = label
        self._client = ContainerClient(
            account_url=f"https://{account}.blob.core.windows.net",
            container_name=container,
            credential=DefaultAzureCredential(),
        )

    def days(self, domain: str) -> list[str]:
        """Jours présents sous un domaine, déduits des préfixes de noms de blobs."""
        jours: set[str] = set()
        for nom in self._client.list_blob_names(name_starts_with=f"{domain}/"):
            morceaux = nom.split("/")
            if len(morceaux) >= 3 and DAY_PATTERN.match(morceaux[1]):
                jours.add(morceaux[1])
        return sorted(jours)

    def list_files(self, domain: str, day: str) -> list[str]:
        """Blobs directement sous `domaine/jour/`, sans descendre plus bas."""
        prefixe = f"{domain}/{day}/"
        noms = []
        for nom in self._client.list_blob_names(name_starts_with=prefixe):
            reste = nom[len(prefixe) :]
            if reste and "/" not in reste and not reste.startswith("."):
                noms.append(reste)
        return sorted(noms)

    def exists(self, source: SourceFile) -> bool:
        return self._client.get_blob_client(source.key).exists()

    def open_read(self, source: SourceFile) -> IO[bytes]:
        """Flux de lecture sur le blob.

        Le SDK ne rend pas d'objet fichier : on lui demande un flux tronçonné et
        on l'expose derrière un fichier temporaire à mémoire bornée. Pour le
        dépôt du CHU, ce tampon **n'est jamais atteint** en pratique — les CSV
        d'identité font quelques centaines de kilo-octets — et il est détruit à
        la fermeture.
        """
        # Pas de `with` ici : le flux est rendu à l'appelant, qui le referme —
        # c'est le contrat de `open_read`, identique à celui de `Path.open`.
        tampon = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX)  # noqa: SIM115
        self._client.get_blob_client(source.key).download_blob().readinto(tampon)
        tampon.seek(0)
        return tampon

    @contextmanager
    def open_write(self, source: SourceFile) -> Iterator[IO[bytes]]:
        """Accumule puis téléverse : un blob n'apparaît qu'une fois complet.

        L'atomicité est celle du stockage objet — il n'existe pas de blob à
        moitié écrit. Ce qui transite par le tampon est déjà pseudonymisé.
        """
        # Pas de `with` ici : la fermeture est garantie par le `finally`, et un
        # `with` fermerait le tampon avant qu'on ait pu le téléverser.
        tampon = tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX)  # noqa: SIM115
        try:
            yield tampon
            tampon.seek(0)
            self._client.get_blob_client(source.key).upload_blob(tampon, overwrite=True)
        finally:
            tampon.close()

    def fingerprint(self, source: SourceFile) -> str:
        with self.open_read(source) as handle:
            return _sha256(handle)

    def table_function(self, source: SourceFile, fmt: str, structure: str | None) -> str:
        return azure_table_function(source, fmt, structure)

    def read_text(self, source: SourceFile) -> str:
        with self.open_read(source) as handle:
            return handle.read().decode("utf-8")


# ── Fabriques ───────────────────────────────────────────────────────────────
def for_source(config: Config) -> Storage:
    """Zone de dépôt du CHU — **lecture seule**, jamais écrite par le pipeline."""
    if config.storage_backend == "azure":
        return AzureBlobStorage(config.storage_account, config.source_container, "dépôt du CHU")
    return LocalStorage(config.source_dir, "dépôt du CHU")


def for_lake(config: Config) -> Storage:
    """Zone de travail pseudonymisée, lue par le moteur."""
    if config.storage_backend == "azure":
        return AzureBlobStorage(config.storage_account, config.lake_container, "lake")
    return LocalStorage(config.lake_dir, "lake")


def publish_file(account: str, container: str, blob_name: str, source: Path) -> str:
    """Dépose un fichier local dans un conteneur, et rend son URL.

    Sert à publier la documentation dbt sur le site statique du compte de
    stockage. Volontairement hors du protocole `Storage` : celui-ci parle de
    fichiers du CHU rangés par domaine et par jour, ce qui n'a rien à voir.
    """
    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobClient, ContentSettings
    except ImportError as exc:  # pragma: no cover - dépend de l'extra `azure`
        raise StorageError("Publication Azure : uv sync --extra azure") from exc

    blob = BlobClient(
        account_url=f"https://{account}.blob.core.windows.net",
        container_name=container,
        blob_name=blob_name,
        credential=DefaultAzureCredential(),
    )
    with source.open("rb") as flux:
        blob.upload_blob(
            flux,
            overwrite=True,
            # Sans ce type, le navigateur télécharge le fichier au lieu de l'afficher.
            content_settings=ContentSettings(content_type="text/html; charset=utf-8"),
        )
    return blob.url


def copy_stream(entree: IO[bytes], sortie: IO[bytes]) -> None:
    """Recopie un flux par blocs : mémoire constante quelle que soit la taille.

    Sur un dépôt réellement volumineux, une copie serveur à serveur
    (`start_copy_from_url`) éviterait de faire transiter les octets par le job.
    Ce n'est pas fait ici : les fichiers concernés ne portent aucune donnée
    identifiante et pèsent quelques mégaoctets — la complexité ne se justifierait pas.
    """
    shutil.copyfileobj(entree, sortie, _CHUNK_SIZE)


def _sha256(flux: IO[bytes]) -> str:
    """Empreinte du contenu, calculée en flux et sans jamais tout charger."""
    digest = hashlib.sha256()
    with flux:
        while chunk := flux.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _litteral(valeur: str) -> str:
    """Littéral SQL. Les valeurs viennent de la configuration, jamais d'une saisie."""
    return "'" + valeur.replace("'", "''") + "'"

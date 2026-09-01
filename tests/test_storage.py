"""Les deux cibles de stockage doivent se comporter identiquement.

Ces tests ne touchent ni Azure ni ClickHouse : ils portent sur ce qui décide de
tout le reste — l'expression SQL rendue au moteur, l'atomicité de l'écriture, et
le fait qu'aucune donnée identifiante n'atteigne la zone de destination, quel que
soit le backend.
"""

from __future__ import annotations

import io
import re

import pytest

from eds.collect import collect
from eds.config import Config
from eds.storage import (
    LocalStorage,
    SourceFile,
    azure_table_function,
    file_table_function,
)

PATIENTS = SourceFile("patients", "2026-08-26", "patients.csv")
MONITORING = SourceFile("monitoring", "2026-08-26", "monitoring.parquet")
STRUCTURE = "patient_pseudo String, birth_year String, sex String, region_code String"


# ── L'expression SQL rendue au moteur ───────────────────────────────────────
def test_le_lecteur_local_est_positionnel():
    """`file(chemin, format, structure)` — le chemin est relatif à `user_files`."""
    assert file_table_function(PATIENTS, "CSVWithNames", STRUCTURE) == (
        f"file('lake/patients/2026-08-26/patients.csv', 'CSVWithNames', '{STRUCTURE}')"
    )


def test_le_lecteur_azure_utilise_des_arguments_nommes():
    """La forme positionnelle ferait lire la structure comme une compression.

    `azureBlobStorage(url, conteneur, chemin, format, structure)` est accepté par
    ClickHouse, mais le cinquième argument y est une *compression* : la structure
    serait alors inférée, en silence. Le typage explicite de bronze disparaîtrait
    sans qu'aucune erreur ne le signale.
    """
    rendu = azure_table_function(PATIENTS, "CSVWithNames", STRUCTURE)
    assert rendu == (
        "azureBlobStorage(lake, blob_path = 'patients/2026-08-26/patients.csv', "
        f"format = 'CSVWithNames', structure = '{STRUCTURE}')"
    )
    assert "structure = " in rendu


def test_aucun_secret_dans_l_expression_azure():
    """Le jeton SAS vit dans la collection nommée, côté serveur.

    S'il apparaissait dans la requête, il finirait dans `system.query_log` — et
    dans les journaux du pipeline le jour où une requête échoue.
    """
    rendu = azure_table_function(PATIENTS, "CSVWithNames", STRUCTURE)
    assert "sig=" not in rendu
    assert "blob.core.windows.net" not in rendu


@pytest.mark.parametrize("rendu", [file_table_function, azure_table_function])
def test_le_parquet_n_impose_aucune_structure(rendu):
    """Parquet porte son propre schéma : le figer casserait au moindre ajout de colonne."""
    assert "structure" not in rendu(MONITORING, "Parquet", None)


@pytest.mark.parametrize("rendu", [file_table_function, azure_table_function])
def test_les_apostrophes_sont_echappees(rendu):
    """Un nom de fichier exotique ne doit pas pouvoir clore un littéral."""
    piege = SourceFile("patients", "2026-08-26", "l'exception.csv")
    assert "''exception" in rendu(piege, "CSVWithNames", None)


# ── Atomicité de l'écriture ─────────────────────────────────────────────────
def test_l_ecriture_est_atomique(tmp_path):
    """Un incident en cours d'écriture ne doit pas laisser de fichier tronqué.

    Un fichier partiel serait chargé au run suivant sans que rien ne le signale :
    l'entrepôt afficherait des comptages faux, et cohérents avec eux-mêmes.
    """
    lake = LocalStorage(tmp_path, "lake")

    with pytest.raises(RuntimeError), lake.open_write(PATIENTS) as sortie:
        sortie.write(b"debut")
        raise RuntimeError("incident en cours d'écriture")

    assert not lake.exists(PATIENTS)
    assert list(tmp_path.rglob("*.tmp")) == [], "un fichier temporaire subsiste"


def test_l_empreinte_est_stable_et_porte_sur_le_contenu(tmp_path):
    """Elle est la clé d'idempotence : deux contenus identiques, une seule empreinte."""
    zone = LocalStorage(tmp_path, "dépôt")
    with zone.open_write(PATIENTS) as sortie:
        sortie.write(b"patient_id,nom\nIPP1,MARTIN\n")

    premiere = zone.fingerprint(PATIENTS)
    assert len(premiere) == 64
    assert zone.fingerprint(PATIENTS) == premiere

    with zone.open_write(PATIENTS) as sortie:
        sortie.write(b"patient_id,nom\nIPP1,BERNARD\n")
    assert zone.fingerprint(PATIENTS) != premiere


# ── La garantie RGPD ne dépend pas du backend ───────────────────────────────
class ZoneEnMemoire:
    """Un `Storage` minimal, pour observer exactement ce qui est écrit.

    Il remplace la zone de destination sans rien changer au reste de la chaîne :
    ce que ce faux reçoit est, octet pour octet, ce que recevrait un conteneur
    de stockage objet.
    """

    label = "zone d'observation"

    def __init__(self) -> None:
        self.contenus: dict[str, bytes] = {}

    def days(self, domain: str) -> list[str]:  # pragma: no cover - non sollicité
        return []

    def exists(self, source: SourceFile) -> bool:
        return source.key in self.contenus

    def open_read(self, source: SourceFile):  # pragma: no cover - non sollicité
        return io.BytesIO(self.contenus[source.key])

    def open_write(self, source: SourceFile):
        zone = self

        class _Tampon(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                zone.contenus[source.key] = self.getvalue()
                return False

        return _Tampon()

    def fingerprint(self, source: SourceFile) -> str:  # pragma: no cover - non sollicité
        return ""

    def table_function(self, source, fmt, structure) -> str:  # pragma: no cover
        return azure_table_function(source, fmt, structure)


def test_aucune_donnee_identifiante_n_atteint_la_zone_de_destination(config: Config):
    """Le contrôle central du projet, vérifié sur un backend qui n'est pas un dossier.

    La pseudonymisation a lieu **dans le flux**, entre la lecture du dépôt et
    l'écriture du lake : elle ne dépend donc pas de la nature de la destination.
    C'est ce qui permet d'affirmer que l'identité en clair ne devient jamais un
    fichier, ni sur disque local ni dans le stockage objet.
    """
    from eds import storage

    depot = storage.for_source(config)
    zone = ZoneEnMemoire()

    for source in (PATIENTS, SourceFile("sejours", "2026-08-26", "sejours.csv")):
        collect(source, depot, zone, config)

    for cle, octets in zone.contenus.items():
        texte = octets.decode("utf-8")
        assert "MARTIN" not in texte, cle
        assert "199017512345678" not in texte, cle
        assert not re.search(r"IPP\d+", texte), cle
        entete = texte.splitlines()[0]
        for colonne in ("nir", "nom", "prenom", "birth_date", "patient_id"):
            assert colonne not in entete, f"{colonne} dans l'en-tête de {cle}"

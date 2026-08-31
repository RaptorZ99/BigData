"""Pseudonymisation des identifiants patients à l'entrée du lake.

Contrainte RGPD du projet : aucune donnée directement identifiante (NIR, nom,
prénom, date de naissance complète) ne doit jamais atteindre l'entrepôt. La
transformation est donc appliquée au moment même de la copie depuis le dépôt du
CHU — l'identité en clair ne quitte pas `source-filestorage/`.

Choix de conception :

* **HMAC-SHA256** plutôt qu'un `sha256(sel + id)` naïf : c'est la construction
  standard pour authentifier une valeur avec une clé, immunisée contre les
  attaques par extension de longueur.
* **Déterministe** : le même IPP produit toujours le même pseudonyme, donc les
  jointures patients ↔ séjours restent valides d'un jour d'ingestion à l'autre.
* **Non réversible** : sans le sel, retrouver l'IPP demanderait de casser
  SHA-256. Le sel vit dans `.env` (gitignoré) et n'est jamais journalisé.
* **Tronqué à 64 bits** : suffisant ici (≈ 10⁻¹² de collision pour 6 000
  patients) et bien plus lisible dans les dashboards qu'un hash de 64 caractères.
"""

from __future__ import annotations

import hashlib
import hmac
import re

# Un pseudonyme = 'P' + 16 caractères hexadécimaux (64 bits de hash).
PSEUDO_PATTERN = re.compile(r"^P[0-9a-f]{16}$")
_PSEUDO_HEX_LENGTH = 16

_ISO_DATE = re.compile(r"^(\d{4})-\d{2}-\d{2}")


class PseudonymizationError(ValueError):
    """Entrée impossible à pseudonymiser de façon fiable."""


def pseudonymize_id(patient_id: str, salt: str) -> str:
    """Transforme un IPP en pseudonyme stable et non réversible.

    >>> pseudonymize_id("IPP0000001", "x" * 32) == pseudonymize_id("IPP0000001", "x" * 32)
    True
    """
    if not salt:
        raise PseudonymizationError("Sel de pseudonymisation vide : ingestion refusée.")
    if not patient_id or not patient_id.strip():
        raise PseudonymizationError("Identifiant patient vide : impossible à pseudonymiser.")

    digest = hmac.new(
        salt.encode("utf-8"), patient_id.strip().encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"P{digest[:_PSEUDO_HEX_LENGTH]}"


def generalize_birth_date(birth_date: str) -> int:
    """Généralise une date de naissance complète en année (minimisation RGPD).

    L'année suffit à tous les usages prévus (tranches d'âge des cohortes) ; le
    jour et le mois sont des quasi-identifiants inutiles, donc supprimés.
    """
    match = _ISO_DATE.match((birth_date or "").strip())
    if not match:
        raise PseudonymizationError(f"Date de naissance illisible : {birth_date!r}")
    return int(match.group(1))

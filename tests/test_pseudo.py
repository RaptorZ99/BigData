"""Garanties attendues de la pseudonymisation (bonus RGPD du sujet)."""

from __future__ import annotations

import pytest

from eds.pseudo import (
    PSEUDO_PATTERN,
    PseudonymizationError,
    generalize_birth_date,
    pseudonymize_id,
)

SALT = "0123456789abcdef0123456789abcdef"
OTHER_SALT = "fedcba9876543210fedcba9876543210"


def test_pseudonyme_stable_pour_un_meme_patient():
    """Sans stabilité, les jointures patients ↔ séjours seraient cassées."""
    assert pseudonymize_id("IPP0000042", SALT) == pseudonymize_id("IPP0000042", SALT)


def test_patients_differents_donnent_pseudonymes_differents():
    assert pseudonymize_id("IPP0000042", SALT) != pseudonymize_id("IPP0000043", SALT)


def test_le_sel_change_totalement_le_pseudonyme():
    """Un sel compromis peut être changé : les anciens pseudonymes deviennent inutilisables."""
    assert pseudonymize_id("IPP0000042", SALT) != pseudonymize_id("IPP0000042", OTHER_SALT)


def test_format_du_pseudonyme():
    pseudo = pseudonymize_id("IPP0000042", SALT)
    assert PSEUDO_PATTERN.match(pseudo), pseudo


def test_le_pseudonyme_ne_laisse_pas_transparaitre_l_identifiant():
    """Non-réversibilité : aucune trace de l'IPP d'origine dans la sortie."""
    pseudo = pseudonymize_id("IPP0000042", SALT)
    assert "IPP" not in pseudo
    assert "0000042" not in pseudo


def test_espaces_superflus_ignores():
    assert pseudonymize_id(" IPP0000042 ", SALT) == pseudonymize_id("IPP0000042", SALT)


@pytest.mark.parametrize("bad_input", ["", "   "])
def test_identifiant_vide_refuse(bad_input: str):
    with pytest.raises(PseudonymizationError):
        pseudonymize_id(bad_input, SALT)


def test_sel_vide_refuse():
    """Mieux vaut ne rien ingérer qu'ingérer sans sel."""
    with pytest.raises(PseudonymizationError):
        pseudonymize_id("IPP0000042", "")


def test_generalisation_de_la_date_de_naissance():
    """Seule l'année entre dans l'entrepôt : le jour et le mois sont supprimés."""
    assert generalize_birth_date("1953-07-14") == 1953


@pytest.mark.parametrize("bad_date", ["", "14/07/1953", "1953", "inconnue"])
def test_date_de_naissance_illisible_refusee(bad_date: str):
    with pytest.raises(PseudonymizationError):
        generalize_birth_date(bad_date)

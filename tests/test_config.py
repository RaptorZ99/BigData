"""Garde-fous de la configuration : ce que le pipeline doit refuser de croire.

La détection des secrets d'exemple est un contrôle de sécurité, pas un confort :
c'est elle qui empêche un entrepôt de santé de tourner avec un mot de passe
publié dans un dépôt Git public. Elle mérite donc d'être testée comme telle,
notamment sur le mode d'échec qui l'a motivée — un mot de passe d'exemple qui
ressemble à un vrai passait auparavant inaperçu.
"""

from __future__ import annotations

import dataclasses

from eds.config import Config


def _avec(config: Config, **remplacements) -> Config:
    return dataclasses.replace(config, **remplacements)


def test_une_configuration_saine_ne_signale_rien(config: Config):
    assert config.weak_password_settings == ()
    assert config.uses_weak_passwords is False


def test_un_secret_d_exemple_est_nomme(config: Config):
    """Le message doit dire QUELLE variable corriger, pas « des mots de passe »."""
    faible = _avec(config, recherche_password="recherche_change_me")

    assert faible.weak_password_settings == ("CLICKHOUSE_RECHERCHE_PASSWORD",)
    assert faible.uses_weak_passwords is True


def test_les_secrets_metabase_sont_couverts(config: Config):
    """Le compte d'administration Metabase ouvre l'accès aux deux connexions.

    Il était le trou de la première version du contrôle : la valeur d'exemple
    « AdminChu2026! » ressemblait à un vrai mot de passe et ne portait aucune
    marque, si bien qu'elle ne déclenchait aucun avertissement.
    """
    faible = _avec(
        config,
        admin_password="Admin_change_me_2026",
        metabase_pilotage_password="Pilotage_change_me_2026",
    )

    assert faible.weak_password_settings == ("MB_ADMIN_PASSWORD", "MB_PILOTAGE_PASSWORD")


def test_la_detection_ignore_la_casse(config: Config):
    """Un modèle recopié en majuscules reste un modèle."""
    assert _avec(config, clickhouse_password="ETL_CHANGE_ME").uses_weak_passwords is True


def test_les_six_secrets_sont_surveilles(config: Config):
    """Aucun secret ne doit sortir du périmètre du contrôle."""
    tous_faibles = _avec(
        config,
        clickhouse_password="change_me",
        pilotage_password="change_me",
        recherche_password="change_me",
        admin_password="change_me",
        metabase_pilotage_password="change_me",
        metabase_recherche_password="change_me",
    )

    assert len(tous_faibles.weak_password_settings) == 6

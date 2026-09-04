"""Le planificateur local lit-il le cron comme Azure, et survit-il à une nuit ratée ?

Le cron par défaut est celui du job Azure ; les deux cibles doivent se déclencher
au même instant UTC. Le reste vérifie les règles classiques d'une expression à
cinq champs et la boucle d'exécution — réessai unique, exception non fatale —
avec une horloge et un sommeil simulés : aucune attente réelle.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from eds import schedule
from eds.schedule import CRON_PAR_DEFAUT, CronError, boucle, parse, prochain_passage

UTC_ = UTC


def instant(texte: str) -> datetime:
    return datetime.strptime(texte, "%Y-%m-%d %H:%M").replace(tzinfo=UTC_)


# ── Lecture de l'expression ─────────────────────────────────────────────────


def test_le_cron_par_defaut_est_celui_du_job_azure():
    """La source de vérité est terraform/variables.tf : `pipeline_cron`."""
    from pathlib import Path

    variables = Path(__file__).resolve().parents[1] / "terraform" / "variables.tf"
    assert f'default     = "{CRON_PAR_DEFAUT}"' in variables.read_text(encoding="utf-8")


def test_lecture_des_cinq_champs():
    cron = parse("5 1 * * *")
    assert cron.minutes == {5}
    assert cron.heures == {1}
    assert cron.jours == frozenset(range(1, 32))
    assert cron.mois == frozenset(range(1, 13))
    assert cron.jours_semaine == frozenset(range(7))
    assert not cron.jour_restreint and not cron.jour_semaine_restreint


@pytest.mark.parametrize(
    ("champ", "attendu"),
    [
        ("*/15", {0, 15, 30, 45}),
        ("1,2,3", {1, 2, 3}),
        ("10-13", {10, 11, 12, 13}),
        ("10-20/5", {10, 15, 20}),
        ("50/5", {50, 55}),
        ("0,30-32", {0, 30, 31, 32}),
    ],
)
def test_listes_plages_et_pas(champ: str, attendu: set[int]):
    assert parse(f"{champ} * * * *").minutes == attendu


def test_dimanche_vaut_0_ou_7():
    assert parse("0 0 * * 7").jours_semaine == {0}
    assert parse("0 0 * * 0,7").jours_semaine == {0}


@pytest.mark.parametrize(
    "expression",
    [
        "5 1 * *",  # quatre champs
        "60 1 * * *",  # minute hors bornes
        "5 24 * * *",  # heure hors bornes
        "5 1 0 * *",  # jour 0
        "5 1 * 13 *",  # mois 13
        "5 1 * * 8",  # jour de semaine 8
        "a 1 * * *",  # pas un nombre
        "*/0 * * * *",  # pas nul
        "10-5 * * * *",  # plage inversée
    ],
)
def test_les_expressions_illisibles_sont_refusees_avec_le_champ_en_cause(expression: str):
    with pytest.raises(CronError):
        parse(expression)


# ── Prochain passage ────────────────────────────────────────────────────────


def test_prochain_passage_du_cron_azure():
    cron = parse(CRON_PAR_DEFAUT)
    assert prochain_passage(cron, instant("2026-09-04 09:40")) == instant("2026-09-05 01:05")
    # Juste avant l'heure : c'est aujourd'hui. À l'heure pile : c'est demain.
    assert prochain_passage(cron, instant("2026-09-04 01:04")) == instant("2026-09-04 01:05")
    assert prochain_passage(cron, instant("2026-09-04 01:05")) == instant("2026-09-05 01:05")


def test_prochain_passage_ignore_les_secondes():
    cron = parse("30 12 * * *")
    apres = instant("2026-09-04 12:29").replace(second=59, microsecond=999_999)
    assert prochain_passage(cron, apres) == instant("2026-09-04 12:30")


def test_prochain_passage_hebdomadaire():
    lundi_6h = parse("0 6 * * 1")
    assert prochain_passage(lundi_6h, instant("2026-09-04 09:40")) == instant("2026-09-07 06:00")


def test_passage_de_mois_et_fin_de_mois():
    cron = parse("0 0 31 * *")
    # Le 31 septembre n'existe pas : le suivant est le 31 octobre.
    assert prochain_passage(cron, instant("2026-09-04 00:00")) == instant("2026-10-31 00:00")


def test_jour_du_mois_ou_jour_de_semaine_quand_les_deux_sont_restreints():
    """Règle Vixie : le 15 du mois OU un lundi."""
    cron = parse("0 9 15 * 1")
    assert prochain_passage(cron, instant("2026-09-04 09:40")) == instant("2026-09-07 09:00")
    assert prochain_passage(cron, instant("2026-09-14 09:40")) == instant("2026-09-15 09:00")


def test_un_cron_annuel_reste_borne():
    cron = parse("0 0 1 1 *")
    assert prochain_passage(cron, instant("2026-09-04 09:40")) == instant("2027-01-01 00:00")


def test_prochain_passage_exige_un_instant_date():
    with pytest.raises(ValueError):
        prochain_passage(parse(CRON_PAR_DEFAUT), datetime(2026, 9, 4, 9, 40))


def test_duree_lisible():
    assert schedule.duree_lisible(timedelta(hours=15, minutes=20)) == "15 h 20"
    assert schedule.duree_lisible(timedelta(days=2, hours=3)) == "2 j 03 h"
    assert schedule.duree_lisible(timedelta(minutes=45)) == "45 min"
    assert schedule.duree_lisible(timedelta(seconds=-5)) == "0 min"


# ── La boucle : horloge et sommeil simulés ──────────────────────────────────


class Horloge:
    """Le temps n'avance que quand on dort."""

    def __init__(self, depart: datetime) -> None:
        self.t = depart
        self.sommeils: list[float] = []

    def maintenant(self) -> datetime:
        return self.t

    def dormir(self, secondes: float) -> None:
        self.sommeils.append(secondes)
        self.t += timedelta(seconds=secondes)


def test_la_boucle_attend_l_heure_puis_execute():
    horloge = Horloge(instant("2026-09-04 23:00"))
    passages: list[datetime] = []

    def executer() -> bool:
        passages.append(horloge.t)
        return True

    n = boucle(
        parse(CRON_PAR_DEFAUT),
        executer,
        maintenant=horloge.maintenant,
        dormir=horloge.dormir,
        max_passages=2,
    )
    assert n == 2
    assert passages == [instant("2026-09-05 01:05"), instant("2026-09-06 01:05")]
    # Sommeil par tranches d'une minute au plus : un arrêt du conteneur n'attend pas.
    assert max(horloge.sommeils) <= 60.0


def test_un_echec_est_reessaye_une_fois_puis_on_attend_le_passage_suivant():
    horloge = Horloge(instant("2026-09-04 01:00"))
    resultats = iter([False, True, True])
    appels: list[datetime] = []

    def executer() -> bool:
        appels.append(horloge.t)
        return next(resultats)

    boucle(
        parse(CRON_PAR_DEFAUT),
        executer,
        delai_reessai=60,
        maintenant=horloge.maintenant,
        dormir=horloge.dormir,
        max_passages=2,
    )
    assert appels == [
        instant("2026-09-04 01:05"),  # échec
        instant("2026-09-04 01:06"),  # réessai, 60 s plus tard
        instant("2026-09-05 01:05"),  # passage suivant, à l'heure
    ]


def test_une_exception_ne_tue_pas_le_planificateur(caplog: pytest.LogCaptureFixture):
    horloge = Horloge(instant("2026-09-04 01:00"))
    compteur = {"n": 0}

    def executer() -> bool:
        compteur["n"] += 1
        raise RuntimeError("entrepôt injoignable")

    with caplog.at_level("ERROR"):
        n = boucle(
            parse(CRON_PAR_DEFAUT),
            executer,
            delai_reessai=1,
            maintenant=horloge.maintenant,
            dormir=horloge.dormir,
            max_passages=1,
        )
    assert n == 1
    assert compteur["n"] == 2  # l'essai, puis le réessai
    assert "entrepôt injoignable" in caplog.text
    assert "Échec confirmé" in caplog.text


# ── Dans la pile Docker Compose ─────────────────────────────────────────────


@pytest.mark.integration
def test_le_planificateur_tourne_dans_la_pile_et_annonce_son_prochain_passage():
    """`make demo` démarre le conteneur `scheduler` ; il attend 01 h 05 UTC."""
    ps = subprocess.run(
        ["docker", "compose", "ps", "--status", "running", "--services"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "scheduler" in ps.stdout.split(), "le service scheduler ne tourne pas"
    journal = subprocess.run(
        ["docker", "compose", "logs", "--no-log-prefix", "scheduler"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "Prochain passage" in journal
    assert f"cron « {CRON_PAR_DEFAUT} »" in journal

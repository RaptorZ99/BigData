"""Planification locale : le même geste que le job Azure, à la même heure.

Sur Azure, `job-eds-pipeline` est un job Container Apps déclenché par un cron
**UTC** (`5 1 * * *`), qui exécute `eds run` dans l'image du pipeline, avec un
réessai en cas d'échec. En local, ce module tient exactement ce rôle : il tourne
dans un conteneur de la pile Docker Compose, construit depuis le même
`Dockerfile`, attend l'heure, exécute le même `eds run`, réessaie une fois, et
recommence. Rien à installer sur le poste : la planification arrive avec
`git clone` et `make demo`, comme le reste.

Deux choix délibérés :

* **le cron est interprété en UTC**, comme sur Azure. Un seul fuseau évite qu'un
  changement d'heure décale silencieusement le traitement — et « 01 h 05 UTC »
  se lit pareil sur le poste et dans le portail ;
* **pas de dépendance** pour lire l'expression. Les cinq champs classiques
  (`*`, listes, plages, pas) tiennent en quelques dizaines de lignes testées, et
  le projet n'a pas à porter une bibliothèque pour une seule ligne de cron.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import time as heure_du_jour

log = logging.getLogger(__name__)

# Expression par défaut : celle du job Azure (terraform/variables.tf, `pipeline_cron`).
CRON_PAR_DEFAUT = "5 1 * * *"

# Bornes de chaque champ, dans l'ordre du cron classique. Le jour de la semaine
# accepte 7 pour dimanche, comme Vixie cron ; il est ramené à 0.
_CHAMPS = (
    ("minute", 0, 59),
    ("heure", 0, 23),
    ("jour du mois", 1, 31),
    ("mois", 1, 12),
    ("jour de la semaine", 0, 7),
)


class CronError(ValueError):
    """Expression cron illisible. Le message dit quel champ, et pourquoi."""


@dataclass(frozen=True, slots=True)
class Cron:
    """Une expression cron à cinq champs, résolue en ensembles de valeurs."""

    expression: str
    minutes: frozenset[int]
    heures: frozenset[int]
    jours: frozenset[int]
    mois: frozenset[int]
    jours_semaine: frozenset[int]
    # Vixie cron : quand le jour du mois ET le jour de la semaine sont tous deux
    # restreints, une date convient si l'un OU l'autre correspond.
    jour_restreint: bool
    jour_semaine_restreint: bool

    def date_convient(self, jour: datetime) -> bool:
        if jour.month not in self.mois:
            return False
        par_jour = jour.day in self.jours
        # Python compte lundi = 0 ; cron compte dimanche = 0.
        par_semaine = (jour.weekday() + 1) % 7 in self.jours_semaine
        if self.jour_restreint and self.jour_semaine_restreint:
            return par_jour or par_semaine
        return par_jour and par_semaine


def parse(expression: str) -> Cron:
    """Lit une expression à cinq champs (`minute heure jour mois jour-semaine`)."""
    champs = expression.split()
    if len(champs) != 5:
        raise CronError(
            f"« {expression} » : cinq champs attendus (minute heure jour mois jour-semaine), "
            f"{len(champs)} trouvé(s)"
        )
    valeurs: list[frozenset[int]] = []
    restreints: list[bool] = []
    for texte, (nom, bas, haut) in zip(champs, _CHAMPS, strict=True):
        ensemble, restreint = _lire_champ(texte, nom, bas, haut)
        valeurs.append(ensemble)
        restreints.append(restreint)
    jours_semaine = frozenset(0 if v == 7 else v for v in valeurs[4])
    return Cron(
        expression=" ".join(champs),
        minutes=valeurs[0],
        heures=valeurs[1],
        jours=valeurs[2],
        mois=valeurs[3],
        jours_semaine=jours_semaine,
        jour_restreint=restreints[2],
        jour_semaine_restreint=restreints[4],
    )


def _lire_champ(texte: str, nom: str, bas: int, haut: int) -> tuple[frozenset[int], bool]:
    """Un champ : `*`, `n`, `a-b`, `*/p`, `a-b/p`, `n/p`, et des listes de tout cela."""
    if texte == "*":
        return frozenset(range(bas, haut + 1)), False

    ensemble: set[int] = set()
    for partie in texte.split(","):
        plage, _, pas_texte = partie.partition("/")
        pas = _entier(pas_texte, nom, partie) if pas_texte else 1
        if pas < 1:
            raise CronError(f"{nom} : pas invalide dans « {partie} »")
        if plage == "*":
            debut, fin = bas, haut
        elif "-" in plage:
            debut_texte, fin_texte = plage.split("-", 1)
            debut, fin = _entier(debut_texte, nom, partie), _entier(fin_texte, nom, partie)
        else:
            debut = _entier(plage, nom, partie)
            # `5/10` : à partir de 5, tous les 10 — jusqu'au bout du champ.
            fin = haut if pas_texte else debut
        if not (bas <= debut <= fin <= haut):
            raise CronError(f"{nom} : « {partie} » sort de l'intervalle {bas}–{haut}")
        ensemble.update(range(debut, fin + 1, pas))
    return frozenset(ensemble), True


def _entier(texte: str, nom: str, partie: str) -> int:
    try:
        return int(texte)
    except ValueError as exc:
        raise CronError(f"{nom} : « {partie} » n'est pas un nombre") from exc


def prochain_passage(cron: Cron, apres: datetime) -> datetime:
    """Premier instant strictement postérieur à `apres` qui satisfait l'expression.

    `apres` doit être en UTC. On avance jour par jour tant que la date ne convient
    pas, puis on prend la première heure-minute admissible : c'est immédiat pour
    un cron quotidien, et borné à 366 jours pour un cron annuel.
    """
    if apres.tzinfo is None:
        raise ValueError("prochain_passage attend un instant en UTC (tzinfo)")
    debut = apres.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    jour = debut
    for _ in range(367):
        if cron.date_convient(jour):
            for h in sorted(cron.heures):
                for m in sorted(cron.minutes):
                    candidat = datetime.combine(jour.date(), heure_du_jour(h, m), tzinfo=UTC)
                    if candidat >= debut:
                        return candidat
        jour = (jour + timedelta(days=1)).replace(hour=0, minute=0)
    raise CronError(f"« {cron.expression} » : aucun passage dans les 366 prochains jours")


def duree_lisible(delta: timedelta) -> str:
    """« 15 h 20 », « 2 j 03 h », « 45 min » — pour le journal, pas pour calculer."""
    total = max(int(delta.total_seconds()), 0)
    jours, reste = divmod(total, 86_400)
    heures, reste = divmod(reste, 3_600)
    minutes = reste // 60
    if jours:
        return f"{jours} j {heures:02d} h"
    if heures:
        return f"{heures} h {minutes:02d}"
    return f"{minutes} min"


def boucle(
    cron: Cron,
    executer: Callable[[], bool],
    *,
    delai_reessai: float = 60.0,
    maintenant: Callable[[], datetime] | None = None,
    dormir: Callable[[float], None] = time.sleep,
    max_passages: int | None = None,
) -> int:
    """Attend chaque passage, exécute, réessaie une fois en cas d'échec.

    `executer` rend vrai si le run a réussi. Une exception qu'il laisserait
    échapper est journalisée et comptée comme un échec : le planificateur ne
    meurt jamais sur une nuit ratée — c'est le comportement d'un job Azure
    (`replica_retry_limit = 1`), et c'est ce qu'on attend d'un service.

    `maintenant` et `dormir` sont injectables pour les tests. La boucle rend le
    nombre de passages effectués (utile avec `max_passages`, infini sinon).
    """
    horloge = maintenant or (lambda: datetime.now(UTC))
    passages = 0
    while max_passages is None or passages < max_passages:
        prochain = prochain_passage(cron, horloge())
        log.info(
            "Prochain passage : %s UTC (dans %s) · cron « %s »",
            prochain.strftime("%Y-%m-%d %H:%M"),
            duree_lisible(prochain - horloge()),
            cron.expression,
        )
        _attendre(prochain, horloge, dormir)
        passages += 1
        log.info("Passage planifié n° %d : démarrage", passages)
        if _essayer(executer):
            continue
        log.warning("Passage en échec ; nouvel essai dans %d s", int(delai_reessai))
        dormir(delai_reessai)
        if _essayer(executer):
            log.info("Nouvel essai réussi")
        else:
            log.error("Échec confirmé ; le prochain passage aura lieu à l'heure prévue")
    return passages


def _attendre(
    instant: datetime, horloge: Callable[[], datetime], dormir: Callable[[float], None]
) -> None:
    """Dort par tranches d'une minute au plus : un arrêt du conteneur n'attend pas."""
    while (reste := (instant - horloge()).total_seconds()) > 0:
        dormir(min(reste, 60.0))


def _essayer(executer: Callable[[], bool]) -> bool:
    try:
        return bool(executer())
    except Exception:  # tout échec doit être journalisé, jamais fatal
        log.exception("Le passage planifié a levé une exception")
        return False

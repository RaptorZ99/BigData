"""Le diagramme d'architecture cloud décrit-il encore l'infrastructure réelle ?

`docs/cloud-architecture.puml` illustre le rapport cloud. Comme le modèle de
données, il ne casse rien quand il ment : une ressource ajoutée à `terraform/`
sans y figurer, ou un job renommé, donnerait un schéma qui n'a plus l'air relu.

Le test ne redessine pas Terraform — un diagramme synthétise. Il vérifie deux
invariants : **chaque ressource Azure nommée dans `terraform/` apparaît sur le
diagramme**, et les paramètres qui commandent l'architecture (taille de VM,
adresses, planification, image) y sont ceux du code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DIAGRAMME = RACINE / "docs" / "cloud-architecture.puml"
TERRAFORM = RACINE / "terraform"


@pytest.fixture(scope="module")
def diagramme() -> str:
    return DIAGRAMME.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def terraform() -> str:
    return "\n".join(f.read_text(encoding="utf-8") for f in sorted(TERRAFORM.glob("*.tf")))


# Les noms de ressources sont construits dans Terraform à partir du préfixe
# `${var.projet}-${var.environnement}`. Ce sont les valeurs par défaut qui sont
# déployées, et c'est sous ces noms que le correcteur les verra dans le portail.
NOMS_RESSOURCES = (
    "rg-eds-chu-prod",
    "vnet-eds-chu-prod",
    "snet-warehouse",
    "snet-jobs",
    "nsg-warehouse-eds-chu-prod",
    "pip-eds-chu-prod",
    "vm-warehouse-eds-chu-prod",
    "cae-eds-chu-prod",
    "job-eds-pipeline",
    "job-eds-provision",
    "job-eds-controle",
    "id-pipeline-eds-chu-prod",
    "log-eds-chu-prod",
    "budget-eds-chu-prod",
    "filestorage",
    "lake",
    "$web",
    "rg-eds-tfstate",
)


@pytest.mark.parametrize("nom", NOMS_RESSOURCES)
def test_chaque_ressource_est_au_diagramme(diagramme: str, nom: str):
    assert nom in diagramme, f"{nom} est déployée par terraform/ mais absente de {DIAGRAMME.name}"


def test_les_jobs_du_diagramme_sont_ceux_de_terraform(diagramme: str, terraform: str):
    """L'inverse compte autant : un job retiré doit quitter le schéma.

    Un job déclaré sous condition (`count = var.… != "" ? 1 : 0`, comme le réveil du
    mode nuit) n'est pas déployé par défaut : le diagramme décrit ce qui tourne, il
    peut l'omettre. Il ne peut en revanche pas montrer un job que Terraform ignore.
    """
    blocs = re.findall(
        r'resource "azurerm_container_app_job" "\w+" \{(.*?)\n\}', terraform, re.DOTALL
    )
    jobs_terraform = {re.search(r'name\s*=\s*"(job-eds-[a-z]+)"', b).group(1): b for b in blocs}
    jobs_par_defaut = {nom for nom, bloc in jobs_terraform.items() if "count " not in bloc}
    jobs_diagramme = set(re.findall(r"job-eds-[a-z]+", diagramme))
    manquants = sorted(jobs_par_defaut - jobs_diagramme)
    assert not manquants, f"jobs déployés par défaut absents du diagramme : {manquants}"
    inconnus = sorted(jobs_diagramme - set(jobs_terraform))
    assert not inconnus, f"jobs au diagramme inconnus de Terraform : {inconnus}"


@pytest.mark.parametrize(
    ("variable", "motif"),
    [
        # Taille de VM : le dimensionnement mémoire de tout le diagramme en découle.
        ("vm_size", r'default\s*=\s*"(Standard_[A-Za-z0-9_]+)"'),
        # Adresses : celles que les règles réseau et les jobs utilisent.
        ("cidr_vnet", r'default\s*=\s*"([0-9./]+)"'),
        ("cidr_warehouse", r'default\s*=\s*"([0-9./]+)"'),
        ("cidr_jobs", r'default\s*=\s*"([0-9./]+)"'),
        # Planification du traitement nocturne.
        ("pipeline_cron", r'default\s*=\s*"([0-9* ]+)"'),
        # Image tirée par les jobs.
        ("eds_image", r'default\s*=\s*"([a-z0-9/-]+):latest"'),
    ],
)
def test_les_parametres_du_diagramme_sont_ceux_du_code(
    diagramme: str, terraform: str, variable: str, motif: str
):
    bloc = re.search(rf'variable "{variable}" \{{.*?\n\}}', terraform, re.DOTALL)
    assert bloc, f"variable {variable} introuvable dans terraform/variables.tf"
    valeur = re.search(motif, bloc.group(0))
    assert valeur, f"défaut de {variable} non reconnu"
    assert valeur.group(1) in diagramme, (
        f"{variable} vaut {valeur.group(1)} dans Terraform mais pas dans {DIAGRAMME.name}"
    )


def test_l_ip_privee_de_la_vm_est_au_diagramme(diagramme: str, terraform: str):
    """`cidrhost(var.cidr_warehouse, 10)` : la dixième adresse du sous-réseau."""
    assert "cidrhost(var.cidr_warehouse, 10)" in terraform
    assert "10.20.1.10" in diagramme


def test_le_rendu_est_a_jour(diagramme: str):
    """`make diagram` régénère le PNG et le SVG ; le rapport cloud embarque le PNG."""
    source = DIAGRAMME.stat().st_mtime
    for rendu in ("eds-cloud-architecture.png", "eds-cloud-architecture.svg"):
        chemin = DIAGRAMME.parent / "img" / rendu
        assert chemin.is_file(), f"{rendu} manquant — lancez `make diagram`"
        assert chemin.stat().st_mtime >= source, (
            f"{rendu} est plus ancien que {DIAGRAMME.name} — lancez `make diagram`"
        )

import csv
import os
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from dotenv import load_dotenv

# Chargement des variables d'environnement
load_dotenv()

# Configuration
CONFLUENCE_URL = os.getenv('CONFLUENCE_URL')
CONFLUENCE_USER = os.getenv('CONFLUENCE_USER')
CONFLUENCE_TOKEN = os.getenv('CONFLUENCE_TOKEN')

# Nettoyage de l'URL de base
if CONFLUENCE_URL and CONFLUENCE_URL.endswith('/'):
    CONFLUENCE_URL = CONFLUENCE_URL[:-1]

# Seuils de fraîcheur (en jours)
DEFAULT_THRESHOLD = 0
RUNBOOK_THRESHOLD = 120

# Éléments obligatoires attendus
REQUIRED_SECTIONS = {
    'default': ['Objectif', 'Description'],
    'runbook': ['Objectif', 'Prérequis', 'Procédure', 'Rollback', 'Contacts']
}


def make_request(endpoint, params=None):
    """Effectue une requête API authentifiée vers Confluence Cloud."""
    # Construction de l'URL : on s'assure d'avoir le bon chemin pour le Cloud
    # Pour le Cloud Atlassian, le chemin est souvent /wiki/rest/api/...
    # On teste d'abord avec /wiki si l'URL est un atlassian.net
    path_prefix = ""
    if "atlassian.net" in CONFLUENCE_URL:
        path_prefix = "/wiki"

    url = f"{CONFLUENCE_URL}{path_prefix}/rest/api/{endpoint}"

    auth = (CONFLUENCE_USER, CONFLUENCE_TOKEN)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    print(f"Tentative de connexion à : {url}")

    try:
        response = requests.get(url, params=params, auth=auth, headers=headers, timeout=30)

        # Debug : Afficher le statut et le début de la réponse en cas de problème
        if response.status_code != 200:
            print(f"--- ERREUR HTTP {response.status_code} ---")
            print(f"Contenu de la réponse : {response.text[:500]}")  # Affiche les 500 premiers caractères
            raise Exception(f"Erreur API {response.status_code}")

        # Vérifier si la réponse est vide
        if not response.text:
            print("--- ERREUR : Réponse vide du serveur ---")
            print("Vérifiez votre URL, votre Token, et que l'utilisateur a accès à l'API.")
            raise Exception("Réponse API vide")

        # Vérifier si la réponse est du HTML (page d'erreur/login) au lieu de JSON
        if not response.text.strip().startswith('{'):
            print("--- ERREUR : La réponse n'est pas du JSON ---")
            print(f"Début de la réponse : {response.text[:200]}")
            raise Exception("Format de réponse invalide (attendu JSON, reçu HTML ou texte)")

        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"Erreur de connexion réseau : {e}")
        raise


def is_runbook(labels_data):
    if not labels_data:
        return False
    results = labels_data.get('results', [])
    for label in results:
        name = ""
        if isinstance(label, dict):
            name = label.get('name', '').lower()
        else:
            name = str(label).lower()
        if 'runbook' in name:
            return True
    return False


def extract_links_and_sections(html_content):
    if not html_content:
        return [], []
    soup = BeautifulSoup(html_content, 'html.parser')
    links = [a['href'] for a in soup.find_all('a', href=True) if a['href'].startswith('http')]
    headings = [tag.get_text(strip=True).lower() for tag in soup.find_all(['h1', 'h2', 'h3', 'h4'])]
    return links, headings


def check_link_validity(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.head(url, timeout=5, allow_redirects=True, headers=headers)
        return response.status_code == 200
    except Exception:
        return False


def audit_pages():
    report_data = []
    print("=== Démarrage de l'audit Confluence ===")

    if not all([CONFLUENCE_URL, CONFLUENCE_USER, CONFLUENCE_TOKEN]):
        print("ERREUR CRITIQUE : Variables d'environnement manquantes dans le fichier .env")
        print(f"URL: {CONFLUENCE_URL}")
        print(f"User: {CONFLUENCE_USER}")
        print(f"Token: {'Défini' if CONFLUENCE_TOKEN else 'Manquant'}")
        return

    cql_query = "type = 'page' ORDER BY lastmodified DESC"
    expand_params = "version,history,labels,body.storage,space"

    start = 0
    limit = 50

    try:
        while True:
            params = {
                'cql': cql_query,
                'start': start,
                'limit': limit,
                'expand': expand_params
            }

            data = make_request('content', params)

            results = data.get('results', [])
            if not results:
                print("Aucun résultat supplémentaire trouvé.")
                break

            print(f"Lot de {len(results)} pages traité.")

            for item in results:
                page_id = item.get('id')
                title = item.get('title')
                space = item.get('space', {})
                space_key = space.get('key', 'N/A') if space else 'N/A'
                link = f"{CONFLUENCE_URL}/wiki/spaces/{space_key}/pages/{page_id}"

                version_info = item.get('version', {})
                last_updated_str = version_info.get('when')
                if not last_updated_str: continue

                last_updated = date_parser.parse(last_updated_str).replace(tzinfo=None)
                days_diff = (datetime.now() - last_updated).days

                labels = item.get('labels')
                is_runbook_page = is_runbook(labels)
                threshold = RUNBOOK_THRESHOLD if is_runbook_page else DEFAULT_THRESHOLD

                freshness_status = f"Obsolète ({days_diff}j)" if days_diff > threshold else "Conforme"

                body_data = item.get('body', {}).get('storage', {})
                html_body = body_data.get('value', '')
                links, headings = extract_links_and_sections(html_body)

                required_key = 'runbook' if is_runbook_page else 'default'
                required_sections = REQUIRED_SECTIONS.get(required_key, [])
                missing_sections = [s for s in required_sections if not any(s.lower() in h for h in headings)]
                structure_status = "Conforme" if not missing_sections else f"Manque: {', '.join(missing_sections)}"

                broken_links = [u for u in links[:5] if not check_link_validity(u)]
                links_status = f"{len(broken_links)} liens brisés" if broken_links else "Liens OK"

                report_data.append({
                    'Titre': title, 'Espace': space_key, 'URL': link,
                    'Type': 'Runbook' if is_runbook_page else 'Standard',
                    'Dernière MAJ': last_updated.strftime('%Y-%m-%d'),
                    'Jours depuis MAJ': days_diff, 'Statut Fraîcheur': freshness_status,
                    'Statut Structure': structure_status, 'Statut Liens': links_status,
                    'Détails Liens Brisés': '; '.join(broken_links)
                })

            if len(results) < limit: break
            start += limit

        print(f"Total pages analysées : {len(report_data)}")

    except Exception as e:
        print(f"Arrêt de l'audit suite à une erreur : {e}")
        return

    if report_data:
        output_file = 'rapport_audit_confluence.csv'
        with open(output_file, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=report_data[0].keys())
            writer.writeheader()
            writer.writerows(report_data)
        print(f"SUCCÈS : Rapport généré dans {output_file}")
    else:
        print("Aucune donnée n'a pu être collectée.")


if __name__ == "__main__":
    audit_pages()

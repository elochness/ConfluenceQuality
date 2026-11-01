# Créer un environnement virtuel

```bash
# Se placer dans le dossier du projet
cd /home/pierre/PycharmProjects/ConfluenceQuality

# Créer un nouvel environnement virtuel nommé '.venv' dans ce dossier
python3 -m venv .venv

# Activer l'environnement
source .venv/bin/activate
```

# Installer les dépendances (requirements.txt)

```bash
pip install -r requirements.txt
```

# Configurer les informations Confluence

```txt
# Indiquer les informations pour se connecter au serveur Confluence
CONFLUENCE_URL=https://home.atlassian.com
CONFLUENCE_USER=votre-email@entreprise.com
CONFLUENCE_TOKEN=votre_token_api
```

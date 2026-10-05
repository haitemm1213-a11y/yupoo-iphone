# Yupoo Photo Downloader — version iPhone

Cette version transforme le programme Tkinter Windows en application web utilisable depuis un iPhone.

## Lancer sur le PC

1. Installer Python 3.11+.
2. Dans ce dossier :

```powershell
py -m pip install -r requirements.txt
py app.py
```

3. Sur le PC, ouvrir `http://127.0.0.1:8080`.

Pour tester depuis l'iPhone sur le même Wi-Fi, utiliser l'adresse IPv4 du PC, par exemple `http://192.168.1.20:8080`.

## Mise en ligne

Pour utiliser l'application depuis l'iPhone même quand le PC est éteint, il faudra ensuite déployer ce dossier sur un hébergeur compatible Python/Flask. Le dossier est volontairement simple pour faciliter cette étape.

from bs4 import BeautifulSoup
import requests
import os
import sqlite3
from datetime import datetime
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional

BASE_URL = 'https://maileg.com'
COLLECTION_BASE_URL = 'https://maileg.com/de/collections/mause'


def lade_produktliste_seite(seite: int) -> List[BeautifulSoup]:
    url = f"{COLLECTION_BASE_URL}?page={seite}"
    print(f"Lade Seite {seite}: {url}")
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Fehler beim Laden der Seite {seite}: {e}")
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    collection = soup.find('div', class_='collection')
    if not collection:
        print("Collection-Bereich nicht gefunden.")
        return []

    items = collection.find_all('li', class_='grid__item')
    return items


def speichere_bild(url: str, ordner: str) -> Optional[str]:
    if not url:
        return None
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Bild konnte nicht heruntergeladen werden: {url}, Fehler: {e}")
        return None

    parsed_url = urlparse(url)
    dateiname = os.path.basename(parsed_url.path)
    pfad = os.path.join(ordner, dateiname)
    try:
        with open(pfad, 'wb') as f:
            f.write(response.content)
    except IOError as e:
        print(f"Bild konnte nicht gespeichert werden: {pfad}, Fehler: {e}")
        return None

    return pfad


def ersetze_groessentext(text: str) -> str:
    if 'Height' in text and 'Net weight' in text:
        text = text.replace('Height', 'Höhe').replace('Net weight', 'Nettogewicht')
    if 'Width' in text:
        text = text.replace('Width', 'Breite')
    if 'Depth' in text:
        text = text.replace('Depth', 'Tiefe')
    return text


def extrahiere_produkt_info(item: BeautifulSoup, img_folder: str) -> Optional[Dict[str, str]]:
    titel_elem = item.select_one('h3.card__heading.h5')
    card_media = item.select_one('div.card__media')
    img_elem = card_media.find('img') if card_media else None
    link_elem = titel_elem.find('a') if titel_elem else None

    if not (titel_elem and img_elem and link_elem and link_elem.get('href')):
        return None

    produkt = {}
    produkt['Titel'] = titel_elem.get_text(strip=True)

    bild_url = img_elem.get('src') or img_elem.get('data-src') or ''
    bild_url = urljoin(BASE_URL, bild_url)
    lokal_pfad = speichere_bild(bild_url, img_folder) or ''
    produkt['Bild Pfad'] = lokal_pfad

    produkt['Produktlink'] = urljoin(BASE_URL, link_elem.get('href'))

    detail_fields = ['Art.-Nr', 'Größen', 'Empfohlenes Alter', 'Primärmaterial', 'Füllungen', 'Pflegehinweise', 'Zertifizierungen', 'Hergestellt in']
    attributes = {field: 'Nicht gefunden' for field in detail_fields}

    try:
        detail_resp = requests.get(produkt['Produktlink'])
        detail_resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Fehler beim Laden der Produktseite {produkt['Produktlink']}: {e}")
        produkt.update(attributes)
        return produkt

    detail_soup = BeautifulSoup(detail_resp.content, 'html.parser')
    need_to_know_box = detail_soup.find('div', class_='NeedtoknowBox')

    if need_to_know_box:
        boxes = need_to_know_box.find_all('div', class_='knoeBox')
        for box in boxes:
            label_elem = box.find('label')
            if label_elem:
                key = label_elem.get_text(strip=True)
                if key in ['Pflegehinweise', 'Zertifizierungen']:
                    icon = box.find('img', class_='icon-img')
                    value = icon.get('title') or icon.get('alt') or 'Nicht angegeben' if icon else 'Nicht angegeben'
                else:
                    wert_elem = box.find('p', class_='mb-0')
                    value = wert_elem.get_text(strip=True) if wert_elem else 'Nicht gefunden'

                if key == 'Größen':
                    value = ersetze_groessentext(value)
                if key == 'Empfohlenes Alter' and value.lower() == 'all ages':
                    value = '0'

                if key in attributes:
                    attributes[key] = value

    produkt.update(attributes)
    return produkt


def setup_database(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS produkte (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            art_nr TEXT,
            titel TEXT,
            bild_pfad TEXT,
            groessen TEXT,
            empfohlenes_alter TEXT,
            primaermaterial TEXT,
            fuellungen TEXT,
            pflegehinweise TEXT,
            zertifizierungen TEXT,
            hergestellt_in TEXT,
            produktlink TEXT UNIQUE
        )
    ''')
    conn.commit()
    return conn


def speichere_produkt(conn: sqlite3.Connection, produkt: Dict[str, str]) -> None:
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO produkte (
            art_nr, titel, bild_pfad, groessen, empfohlenes_alter, primaermaterial,
            fuellungen, pflegehinweise, zertifizierungen, hergestellt_in, produktlink
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(produktlink) DO UPDATE SET
            art_nr=excluded.art_nr,
            titel=excluded.titel,
            bild_pfad=excluded.bild_pfad,
            groessen=excluded.groessen,
            empfohlenes_alter=excluded.empfohlenes_alter,
            primaermaterial=excluded.primaermaterial,
            fuellungen=excluded.fuellungen,
            pflegehinweise=excluded.pflegehinweise,
            zertifizierungen=excluded.zertifizierungen,
            hergestellt_in=excluded.hergestellt_in
    ''', (
        produkt.get('Art.-Nr'), produkt.get('Titel'), produkt.get('Bild Pfad'), produkt.get('Größen'), produkt.get('Empfohlenes Alter'),
        produkt.get('Primärmaterial'), produkt.get('Füllungen'), produkt.get('Pflegehinweise'), produkt.get('Zertifizierungen'),
        produkt.get('Hergestellt in'), produkt.get('Produktlink')
    ))
    conn.commit()


def scraper():
    img_folder = 'img'
    db_folder = 'db'
    os.makedirs(img_folder, exist_ok=True)
    os.makedirs(db_folder, exist_ok=True)

    db_path = os.path.join(db_folder, 'maileg.db')
    conn = setup_database(db_path)

    seite = 1
    total = 0
    while True:
        items = lade_produktliste_seite(seite)
        if not items:
            break

        for item in items:
            produkt_info = extrahiere_produkt_info(item, img_folder)
            if produkt_info:
                speichere_produkt(conn, produkt_info)
                total += 1

        seite += 1

    print(f"Gesamtzahl erfasster Produkte: {total}")
    print(f"Datenbank liegt unter: '{db_path}'")
    print(f"Bilder gespeichert in: '{img_folder}'")


if __name__ == '__main__':
    scraper()

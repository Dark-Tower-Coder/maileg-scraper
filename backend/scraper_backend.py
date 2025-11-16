from bs4 import BeautifulSoup
import requests
import os
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional
import time

BASE_URL = 'https://maileg.com'
COLLECTION_BASE_URL = 'https://maileg.com/de/collections/mause'

MATERIAL_TRANSLATION = {
    'Cotton': 'Baumwolle',
    'Polyester': 'Polyester',
    'Cardboard': 'Karton',
    'Wood': 'Holz',
    'Ramie': 'Ramie',
    'Linen': 'Leinen',
    'Metal': 'Metall'
}

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

def extrahiere_preis(detail_soup: BeautifulSoup) -> str:
    preis = 'Nicht gefunden'
    preis_container = detail_soup.select_one('div.price__container')
    if preis_container:
        sale_price = preis_container.select_one('span.price-item--sale')
        if sale_price and sale_price.get_text(strip=True):
            preis = sale_price.get_text(strip=True)
        else:
            regular_price = preis_container.select_one('span.price-item--regular')
            if regular_price and regular_price.get_text(strip=True):
                preis = regular_price.get_text(strip=True)
    return preis

def split_materialen(material_str: Optional[str]) -> List[str]:
    if not material_str or material_str == 'Nicht gefunden':
        return []
    materialien_raw = [m.strip() for m in material_str.replace(',', '/').split('/')]
    materialien = []
    for m in materialien_raw:
        trans = MATERIAL_TRANSLATION.get(m)
        materialien.append(trans if trans else m)
    return materialien

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
    attributes = {
        'Art.-Nr': 'Nicht gefunden',
        'Größen': 'Nicht gefunden',
        'Empfohlenes Alter': 'Nicht gefunden',
        'Primärmaterial': 'Nicht gefunden',
        'Füllungen': 'Nicht gefunden',
        'Pflegehinweise': 'Nicht gefunden',
        'Zertifizierungen': 'Nicht gefunden',
        'Hergestellt in': 'Nicht gefunden'
    }

    try:
        detail_resp = requests.get(produkt['Produktlink'])
        detail_resp.raise_for_status()
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
    except requests.RequestException as e:
        print(f"Fehler beim Laden der Produktseite {produkt['Produktlink']}: {e}")
        return produkt  # Rückgabe mit den bisher gesammelten Daten, wenn Fehler

    produkt.update(attributes)
    produkt['Preis'] = extrahiere_preis(detail_soup if 'detail_soup' in locals() else None)
    produkt['Materialien'] = split_materialen(produkt.get('Primärmaterial'))

    return produkt

def setup_database(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS produkte (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            art_nr TEXT UNIQUE,
            titel TEXT,
            bild_pfad TEXT,
            groessen TEXT,
            empfohlenes_alter TEXT,
            hersteller_id INTEGER,
            FOREIGN KEY(hersteller_id) REFERENCES attribute(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS preise (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produkt_id INTEGER,
            preis TEXT,
            zeitstempel TEXT,
            quelle_id INTEGER,
            produktlink TEXT,
            FOREIGN KEY(produkt_id) REFERENCES produkte(id),
            FOREIGN KEY(quelle_id) REFERENCES quellen(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quellen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            url TEXT UNIQUE
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attribute (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            typ TEXT,
            name TEXT,
            UNIQUE(typ, name)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS produkte_attribute (
            produkt_id INTEGER,
            attribute_id INTEGER,
            PRIMARY KEY (produkt_id, attribute_id),
            FOREIGN KEY (produkt_id) REFERENCES produkte(id),
            FOREIGN KEY (attribute_id) REFERENCES attribute(id)
        )
    ''')
    conn.commit()
    return conn

def hole_attribut_id(conn, typ, name):
    if not name or name == 'Nicht gefunden':
        return None
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM attribute WHERE typ=? AND name=?', (typ, name))
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute('INSERT INTO attribute (typ, name) VALUES (?, ?)', (typ, name))
    conn.commit()
    return cursor.lastrowid

def hole_quelle_id(conn, name, url):
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM quellen WHERE url=?', (url,))
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute('INSERT INTO quellen (name, url) VALUES (?, ?)', (name, url))
    conn.commit()
    return cursor.lastrowid

def hole_letzten_preis(conn, produkt_id):
    cursor = conn.cursor()
    cursor.execute('SELECT preis FROM preise WHERE produkt_id=? ORDER BY zeitstempel DESC LIMIT 1', (produkt_id,))
    row = cursor.fetchone()
    return row[0] if row else None

def hole_art_nr(conn, produkt_id):
    cursor = conn.cursor()
    cursor.execute('SELECT art_nr FROM produkte WHERE id=?', (produkt_id,))
    row = cursor.fetchone()
    return row[0] if row else None

def speichere_produkt(conn, produkt):
    cursor = conn.cursor()
    hersteller_id = hole_attribut_id(conn, 'hersteller', produkt.get('Hergestellt in'))

    cursor.execute('''
        INSERT INTO produkte (art_nr, titel, bild_pfad, groessen, empfohlenes_alter, hersteller_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(art_nr) DO UPDATE SET
            titel=excluded.titel,
            bild_pfad=excluded.bild_pfad,
            groessen=excluded.groessen,
            empfohlenes_alter=excluded.empfohlenes_alter,
            hersteller_id=excluded.hersteller_id
    ''', (
        produkt.get('Art.-Nr'), produkt.get('Titel'), produkt.get('Bild Pfad'), produkt.get('Größen'),
        produkt.get('Empfohlenes Alter'), hersteller_id
    ))
    conn.commit()

    produkt_id = cursor.execute('SELECT id FROM produkte WHERE art_nr=?', (produkt.get('Art.-Nr'),)).fetchone()[0]

    for material in produkt.get('Materialien', []):
        attr_id = hole_attribut_id(conn, 'material', material)
        if attr_id:
            cursor.execute('INSERT OR IGNORE INTO produkte_attribute (produkt_id, attribute_id) VALUES (?, ?)', (produkt_id, attr_id))

    for typ, feld in [('fuellung', 'Füllungen'), ('pflegehinweis', 'Pflegehinweise'), ('zertifizierung', 'Zertifizierungen')]:
        attr_id = hole_attribut_id(conn, typ, produkt.get(feld))
        if attr_id:
            cursor.execute('INSERT OR IGNORE INTO produkte_attribute (produkt_id, attribute_id) VALUES (?, ?)', (produkt_id, attr_id))

    conn.commit()
    return produkt_id

def speichere_preis(conn, produkt_id, preis, produktlink, quelle_name, quelle_url):
    letzte_preis = hole_letzten_preis(conn, produkt_id)
    art_nr = hole_art_nr(conn, produkt_id) or 'unbekannt'
    if letzte_preis == preis:
        print(f"Kein neuer Preis für Art.-Nr {art_nr}. Überspringe.")
        return
    quelle_id = hole_quelle_id(conn, quelle_name, quelle_url)
    zeitstempel = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO preise (produkt_id, preis, zeitstempel, quelle_id, produktlink) VALUES (?, ?, ?, ?, ?)
    ''', (produkt_id, preis, zeitstempel, quelle_id, produktlink))
    conn.commit()
    print(f"Preis aktualisiert für Art.-Nr {art_nr}: {preis}")

def scraper():
    start = time.time()
    img_folder = 'img'
    db_folder = 'db'
    os.makedirs(img_folder, exist_ok=True)
    os.makedirs(db_folder, exist_ok=True)
    db_path = os.path.join(db_folder, 'maileg.db')
    conn = setup_database(db_path)

    seite = 1
    total = 0
    quelle_name = "maileg.com"
    quelle_url = COLLECTION_BASE_URL

    while True:
        items = lade_produktliste_seite(seite)
        if not items:
            break
        for item in items:
            produkt_info = extrahiere_produkt_info(item, img_folder)
            if produkt_info:
                produkt_id = speichere_produkt(conn, produkt_info)
                speichere_preis(conn, produkt_id, produkt_info.get('Preis'),
                                produkt_info.get('Produktlink'), quelle_name, quelle_url)
                total += 1
        seite += 1

    dauer = time.time() - start
    print(f"Gesamtzahl erfasster Produkte: {total}")
    print(f"Laufzeit des Durchlaufs: {dauer:.2f} Sekunden")
    print(f"Datenbank liegt unter: '{db_path}'")
    print(f"Bilder gespeichert in: '{img_folder}'")

if __name__ == '__main__':
    import time
    scraper()

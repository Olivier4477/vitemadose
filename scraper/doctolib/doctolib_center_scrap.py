import json
import time
import traceback

import requests
from bs4 import BeautifulSoup

from scraper.ordoclic import cp_to_insee
from utils.vmd_logger import enable_logger_for_production

BASE_URL = 'https://www.doctolib.fr/vaccination-covid-19/france?page={0}'
BOOKING_URL = 'https://www.doctolib.fr/booking/{0}.json'

CENTER_TYPES = [
    'hopital-public',
    'centre-de-vaccinations-internationales',
    'centre-de-sante',
    'pharmacie',
    'medecin-generaliste',
    'centre-de-vaccinations-internationales',
    'centre-examens-de-sante'
]


def parse_doctolib_business_hours(url_data, place):
    # Opening hours
    business_hours = dict()
    keys = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    if not place['opening_hours']:
        return url_data

    for opening_hour in place['opening_hours']:
        format_hours = ''
        key_name = keys[opening_hour['day'] - 1]
        if not opening_hour.get('enabled', False):
            business_hours[key_name] = None
            continue
        for range in opening_hour['ranges']:
            if len(format_hours) > 0:
                format_hours += ', '
            format_hours += f'{range[0]}-{range[1]}'
        business_hours[key_name] = format_hours

    if business_hours:
        url_data['business_hours'] = business_hours
    return url_data


def get_doctolib_center_data(url_data):
    data = requests.get(BOOKING_URL.format(url_data['internal_api_name']))
    data.raise_for_status()
    output = data.json().get('data', {})

    url_data['gid'] = f'd{output.get("profile", {}).get("id", 0)}'[:8]

    # Parse place
    place = output.get('places', {})
    if not place:
        return url_data
    place = place[0]  # for the moment

    # Parse place location
    url_data['address'] = place['full_address']
    url_data['long_coor1'] = place['longitude']
    url_data['lat_coor1'] = place['latitude']
    url_data["com_insee"] = cp_to_insee(place["zipcode"])

    url_data = parse_doctolib_business_hours(url_data, place)
    return url_data


def is_revelant_url(url):
    href = url.get('href')
    is_center = False
    if len(href.split('/')) < 3:
        return False

    for center_type in CENTER_TYPES:
        if href.startswith(f'/{center_type}/'):
            is_center = True
            break

    if not is_center or not url.contents or not url.contents[0]:
        return False
    if not url.div or url.img:
        return False
    return True


def scrape_page(page_id):
    data = requests.get(BASE_URL.format(page_id))
    data.raise_for_status()
    output = data.text
    soup = BeautifulSoup(output)
    center_urls = []

    for link in soup.findAll("a"):
        href = link.get('href')
        if not is_revelant_url(link):
            continue
        vp = str(link.div.string)
        if href in center_urls:
            continue
        api_name = href.split('/')[-1]
        center_data = {'rdv_site_web': href, 'nom': vp, 'internal_api_name': api_name}
        center_data = get_doctolib_center_data(center_data)
        if not center_data:
            continue
        center_urls.append(center_data)
    return center_urls


def main():
    logger = enable_logger_for_production()
    center_urls = []
    i = 1
    while i < 2000:
        try:
            centr = scrape_page(i)
            if len(centr) == 0:
                break
            center_urls.extend(centr)
            logger.info("Center total : {0} | Current page: {1} | Center page: {2}".format(len(center_urls), i, len(centr)))
            i += 1
        except Exception as e:
            traceback.print_exc()
            logger.warning("Unable to scrape Doctolib page {0}".format(i))
    if len(center_urls) == 0:
        logger.error("No Doctolib center found. Banned?")
        exit(1)
    file = open('data/output/doctolib-centers.json', 'w')
    file.write(json.dumps(center_urls, indent=2))
    file.close()
    logger.info("Doctolib center scrapped: {0}".format(center_urls))


if __name__ == "__main__":
    main()

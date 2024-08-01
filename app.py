from flask import Flask, request, jsonify, render_template
import requests
from PIL import Image
from io import BytesIO
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
import re
import os
from datetime import datetime, timezone
import random

app = Flask(__name__)

def login_and_get_cookies(email, senha):
    login_url = "https://app.jetimob.com/"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        page.goto(login_url)
        
        page.fill('input[placeholder="exemplo@email.com"]', email)
        page.fill('input[placeholder="Digite sua senha"]', senha)
        page.click('button[type="submit"]')
        
        page.wait_for_load_state('networkidle')

        page.reload()

        cookies = page.context.cookies()
        browser.close()
        
        return cookies

def get_suggested_code(cookies):
    url = "https://app.jetimob.com/api/imoveis/novo"
    headers = {
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, como Gecko) Chrome/126.0.0.0 Safari/537.36',
        'X-App-Version': '20240718-0',
        'X-Requested-With': 'XMLHttpRequest',
        'X-Timezone': 'America/Sao_Paulo'
    }
    cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies}
    response = requests.get(url, headers=headers, cookies=cookies_dict)
    response.raise_for_status()
    data = response.json()
    return data["data"]["suggested_code"]

def get_city_id(city_name, cities):
    for city in cities:
        if city["name"].lower() == city_name.lower():
            return city["id"]
    return None

def get_neighborhoods_id(neighborhood_name, neighborhoods):
    for neighborhood in neighborhoods:
        if neighborhood["name"].lower() == neighborhood_name.lower():
            return neighborhood["id"]
    return None

def map_property_type(description, property_types):
    description = description.lower()
    for property_type in property_types:
        if property_type['label'].lower() in description:
            return property_type['id']
    return 12

def extract_data(url, cookies, property_types):
    cookies_dict = {cookie['name']: cookie['value'] for cookie in cookies}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        page.goto(url)
        
        page.wait_for_load_state('networkidle')

        images = []
        picture_tags = page.query_selector_all("ul.carousel-photos--wrapper li.carousel-photos--item picture source[type='image/webp']")
        for picture in picture_tags:
            img_url = picture.get_attribute("srcset")
            if img_url:
                img_url = img_url.split()[0]
                images.append(img_url)
        
        if not os.path.exists('img'):
            os.makedirs('img')
        
        for idx, img_url in enumerate(images):
            img_response = requests.get(img_url, cookies=cookies_dict)
            img = Image.open(BytesIO(img_response.content)).convert('RGB')
            img_path = f'img/img_{idx}.jpeg'
            
            if len(img_response.content) > 50 * 1024 * 1024:
                img.save(img_path, format='JPEG', quality=85)
            else:
                img.save(img_path, format='JPEG')
        
        content = page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        scripts = soup.find_all('script', type='application/ld+json')
        
        breadcrumb_data = None
        product_data = None
        
        for script in scripts:
            script_content = json.loads(script.string)
            if "@type" in script_content:
                if script_content["@type"] == "BreadcrumbList":
                    breadcrumb_data = script_content
                elif script_content["@type"] == "Product":
                    product_data = script_content
        
        if not breadcrumb_data or not product_data:
            raise ValueError("Não foi possível encontrar os dados necessários na página.")
        
        localidade = " > ".join([item["item"]["name"] for item in breadcrumb_data.get("itemListElement", [])])
        
        nome = product_data.get("name", None)
        descricao = product_data.get("description", None)
        preco = product_data.get("offers", {}).get("price", None)
        
        business_type_tag = soup.find('p', id='business-type-info')
        business_type = business_type_tag.text.strip() if business_type_tag else None
        
        price_info_tag = soup.find('p', {'data-testid': 'price-info-value'})
        price_info = re.sub(r'\D', '', price_info_tag.text.strip()) if price_info_tag else None
        
        condo_fee_price_tag = soup.find('span', id='condo-fee-price')
        condo_fee_price = re.sub(r'\D', '', condo_fee_price_tag.text.strip()) if condo_fee_price_tag else None
        
        iptu_price_tag = soup.find('span', id='iptu-price')
        iptu_price = re.sub(r'\D', '', iptu_price_tag.text.strip()) if iptu_price_tag else None
        
        iptu_period_tag = soup.find('span', {'class': 'l-text--variant-body-regular l-text--weight-regular undefined'})
        iptu_period = iptu_period_tag.text.strip().lower() if iptu_period_tag else "ano"
        
        address_info_tag = soup.find('p', {'data-testid': 'address-info-value'})
        address_info = address_info_tag.text.strip() if address_info_tag else None
        
        area = 0
        quartos = 0
        banheiros = 0
        vagas = 0
        suites = 0
        andar = "N/A"
        varanda = "N/A"

        amenities_items = soup.find_all('p', class_='amenities-item')
        amenities = []
        for item in amenities_items:
            text = item.text.strip()
            amenities.append(text)
            if "m²" in text:
                area = re.sub(r'\D', '', text)
            elif "quartos" in text:
                quartos = re.sub(r'\D', '', text)
            elif "banheiros" in text:
                banheiros = re.sub(r'\D', '', text)
            elif "vagas" in text:
                vagas = re.sub(r'\D', '', text)
            elif "andar" in text:
                andar = re.sub(r'\D', '', text)
            elif "Varanda" in text:
                varanda = text

        if vagas == 0 or suites == 0:
            descricao_lower = descricao.lower()
            vagas_match = re.search(r'\d+\s*vagas?', descricao_lower) or re.search(r'uma\s*vaga', descricao_lower)
            suites_match = re.search(r'\d+\s*suites?', descricao_lower) or re.search(r'uma\s*suíte', descricao_lower)
            if vagas_match:
                vagas = int(re.search(r'\d+', vagas_match.group()).group())
            if suites_match:
                suites = int(re.search(r'\d+', suites_match.group()).group())
        
        created_at_tag = soup.find('span', class_='description__created-at')
        created_at = created_at_tag.text.strip() if created_at_tag else "N/A"
        
        property_type_id = map_property_type(descricao, property_types)

        return {
            "localidade": localidade,
            "nome": nome,
            "descricao": descricao,
            "preco_imovel": int(price_info) * 100,
            "tipo_negocio": business_type,
            "preco_condominio": int(condo_fee_price) * 100,
            "preco_iptu": int(iptu_price) * 100,
            "iptu_period": iptu_period,
            "area": area,
            "quartos": quartos,
            "banheiros": banheiros,
            "vagas": vagas,
            "suites": suites,
            "andar": andar,
            "varanda": varanda,
            "amenities": amenities,
            "images": images,
            "created_at": created_at,
            "endereco": address_info,
            "type": property_type_id
        }

def resize_image(image_path, max_size=15 * 1024 * 1024):
    img = Image.open(image_path)
    img_format = img.format
    img_io = BytesIO()
    
    img.save(img_io, format=img_format)
    img_size = img_io.tell()
    
    if img_size <= max_size:
        return image_path

    quality = 90
    while img_size > max_size and quality > 10:
        img_io = BytesIO()
        img.save(img_io, format=img_format, quality=quality)
        img_size = img_io.tell()
        quality -= 10

    img_io.seek(0)
    with open(image_path, 'wb') as out_file:
        out_file.write(img_io.read())
    
    return image_path

def upload_image(cookies, image_path):
    image_path = resize_image(image_path)
    if os.path.getsize(image_path) > 15 * 1024 * 1024:
        raise ValueError(f"Imagem {image_path} ainda é maior que 15MB após redimensionamento.")

    url = "https://app.jetimob.com/api/upload-image"
    headers = {
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'Origin': 'https://app.jetimob.com',
        'Referer': 'https://app.jetimob.com/imoveis/novo',
        'Sec-CH-UA': '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
        'Sec-CH-UA-Mobile': '?0',
        'Sec-CH-UA-Platform': '"Linux"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, como Gecko) Chrome/126.0.0.0 Safari/537.36',
    }
    
    session = requests.Session()
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', 'jetimob.com'))

    mime_type = 'image/jpeg' if image_path.lower().endswith('.jpeg') else 'image/png'

    with open(image_path, 'rb') as img_file:
        files = {
            'file': (os.path.basename(image_path), img_file, mime_type),
            'category': (None, '1')
        }
        
        response = session.post(url, headers=headers, files=files)
        
        if response.status_code == 200:
            return response.json()["data"]["url"], response.json()["data"]["image_id"]
        else:
            raise ValueError(f"Erro ao fazer upload da imagem: {response.status_code} - {response.text}")

def create_property(cookies, payload):
    url = "https://app.jetimob.com/api/imoveis/novo"
    headers = {
        'Accept': 'application/json',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        'Origin': 'https://app.jetimob.com',
        'Referer': 'https://app.jetimob.com/imoveis/novo',
        'Sec-CH-UA': '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
        'Sec-CH-UA-Mobile': '?0',
        'Sec-CH-UA-Platform': '"Linux"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, como Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Content-Type': 'application/json',
        'X-App-Version': '20240718-0',
        'X-Requested-With': 'XMLHttpRequest',
        'X-Timezone': 'America/Sao_Paulo'
    }

    session = requests.Session()
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', 'jetimob.com'))
    
    response = session.post(url, headers=headers, json=payload)
    
    if response.status_code == 200 or response.status_code == 201:
        return response.json()
    else:
        raise ValueError(f"Erro ao criar imóvel: {response.status_code} - {response.text}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/cadastrar-imovel', methods=['POST'])
def cadastrar_imovel():
    try:
        url = request.json['url']
        
        email = "contatosfoc@gmail.com"
        senha = "24052305"

        cookies = login_and_get_cookies(email, senha)
        editable_code = get_suggested_code(cookies)

        with open('./data/property_types.json', 'r', encoding='utf-8') as f:
            property_types = json.load(f)

        data = extract_data(url, cookies, property_types)

        endereco_regex = re.compile(r'^(.*?)(?:, (\d+))? - (.*?), (.*?)(?: - (.*))?$')

        match = endereco_regex.match(data['endereco'])

        rua = match.group(1) if match and match.group(1) != None else "Av. Olegário Maciel"
        numero = match.group(2) if match and match.group(2) != None else str(random.randint(0, 1000))
        neighborhood = match.group(3) if match and match.group(3) != None else "3420"

        with open('./data/neighborhoods.json', 'r', encoding='utf-8') as f:
            neighborhoods = json.load(f)

        neighborhood_id = get_neighborhoods_id(neighborhood, neighborhoods)

        city_id = 2754
        observation_internal = f"URL do imóvel: {url}\n{data['created_at']}"

        images_payload = []
        for idx, img_url in enumerate(data['images']):
            img_path = f'img/img_{idx}.jpeg'
            blob_url, image_id = upload_image(cookies, img_path)
            img_size = os.path.getsize(img_path)
            images_payload.append({
                "name": f"Image {idx}",
                "size": str(img_size),
                "url": blob_url,
                "selected": False,
                "id": image_id,
                "visible": True
            })

        current_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000000Z')
        current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        iptu_monthly = data['iptu_period'] != 'ano'

        payload = {
            "property_id": None,
            "floor": int(data['andar']) if data['andar'].isdigit() else 0,
            "address_visibility": 8,
            "agent": {
                "label": "Teste Samuel",
                "person_id": 3328137,
                "image": "https://avatar.jetimob.com/Teste Samuel",
                "user_system_id": 69914,
                "deleted": False
            },
            "agency_date": current_date,
            "email_time_gap": None,
            "building_status": 4,
            "building_type": None,
            "city": city_id,
            "cleaning_fee_price": "",
            "surety_fire_price": "",
            "code": "",
            "editable_code": editable_code,
            "complement": "",
            "condominium": None,
            "condominium_price": int(data['preco_condominio']),
            "condominium_price_visible": True,
            "condominium_is_exempt": False,
            "subcondominium": None,
            "typology": None,
            "contracts": [
                {
                    "id": 1,
                    "available": True,
                    "commission_percentage": 0.06,
                    "commission_cents": None,
                    "unavailable_reason": None,
                    "price": int(data['preco_imovel']),
                    "visible": True,
                    "index_readjustment_id": None
                }
            ],
            "deadline_date": None,
            "exclusivity": False,
            "exclusivity_date": None,
            "garages": int(data['vagas']),
            "suites": data['suites'],
            "bedrooms": int(data['quartos']),
            "bathrooms": int(data['banheiros']),
            "position": None,
            "facilities": [
                19,
                30
            ],
            "facilitiesGroups": [],
            "floor_types": [],
            "solar_orientations": [],
            "total_area": int(data['area']),
            "useful_area": None,
            "arable_area": None,
            "financeable": 1,
            "furnished": 0,
            "interchanges": [],
            "iptu_price": int(data['preco_iptu']),
            "iptu_record": "",
            "iptu_visible": True,
            "iptu_monthly": iptu_monthly,
            "iptu_is_exempt": False,
            "latitude": -19.9550216,
            "longitude": -43.941872,
            "neighborhood": neighborhood_id,
            "number": numero,
            "title": data['nome'],
            "observation_external": data['descricao'][:150],
            "meta_title": data['nome'][:70],
            "meta_description": data['descricao'][:150],
            "observation_internal": observation_internal,
            "person_owners": [
                {
                    "person": {
                        "name": "Appê Plus",
                        "social_name": "Appê Plus",
                        "system_id": 16330,
                        "created_by": 69914,
                        "updated_by": 69914,
                        "updated_at": current_time,
                        "created_at": current_time,
                        "person_id": 3338628,
                        "person_individual_id": 2060547,
                        "email": None,
                        "phone": None
                    },
                    "percentage": 100
                }
            ],
            "people_quantity": None,
            "private_area": None,
            "property_board": False,
            "registration_record": "",
            "water_record": "",
            "gas_record": "",
            "energy_record": "",
            "broker": {
                "label": "Teste Samuel",
                "person_id": 3328137,
                "image": "https://avatar.jetimob.com/Teste Samuel",
                "user_system_id": 69914,
                "deleted": False
            },
            "rural_activity": [],
            "rural_headquarters": None,
            "sea_distance": None,
            "occupation": 3,
            "season_calendars": [],
            "season_unavailable": [],
            "state": 17,
            "reference": "",
            "street": rua,
            "street_id": None,
            "surety_warranty": None,
            "labels": [],
            "terrain_total_area": None,
            "terrain_length_left": None,
            "terrain_length_right": None,
            "terrain_width_back": None,
            "terrain_width_front": None,
            "ceiling_height": None,
            "type": data['type'],
            "typeCategory": "Residencial",
            "approved": None,
            "zipcode": None,
            "keys": [],
            "map_visibility": 2,
            "images": images_payload,
            "blueprints": [],
            "files_ids": [],
            "tours": [],
            "videos": [],
            "unapproval_observation": None,
            "boxes": [],
            "google_earth_url": None,
            "portal_property": {
                "18225": {
                    "active": True,
                    "highlight": {
                        "label": "Sem destaque",
                        "value": 0
                    },
                    "portal_property_id": None
                }
            }
        }

        response = create_property(cookies, payload)

        import pprint
        pprint.pprint(response)
        
        return response, 200
    
        

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

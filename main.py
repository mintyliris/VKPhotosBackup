"""
VK Photos Backup - программа для загрузки фотографий из VK на Яндекс.Диск.
Основной файл приложения, содержащий всю логику работы с API и обработки запросов.
"""

import os
import requests
import json
import logging
from datetime import datetime
from flask import Flask, request, redirect, session, render_template, flash, jsonify
from config import *

# Инициализация Flask приложения
app = Flask(__name__)
app.secret_key = SECRET_KEY

# Настройка системы логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@app.route('/')
def index():
    """Отображение главной страницы приложения."""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    """
    Обработка POST-запроса для загрузки фотографий.
    Получает данные из формы и инициирует процесс загрузки.
    """
    try:
        # Получение данных из формы
        user_id = request.form.get('user_id')
        yandex_token = request.form.get('yandex_token')
        folder_path = request.form.get('folder_path')
        
        logger.info(f'Получен запрос на загрузку. User ID: {user_id}, Folder: {folder_path}')
        
        # Проверка наличия обязательных параметров
        if not all([user_id, yandex_token]):
            error_msg = 'Не указан ID пользователя VK или токен Яндекс.Диска'
            logger.error(error_msg)
            return jsonify({
                'error': error_msg,
                'success': False
            }), 400
        
        try:
            logger.info(f'Начало загрузки фотографий для пользователя {user_id}')
            uploaded_photos = upload_photos_to_yandex_disk(user_id, VK_ACCESS_TOKEN, yandex_token, folder_path)
            
            success_message = f'Успешно загружено {len(uploaded_photos)} фотографий'
            logger.info(success_message)
            
            return jsonify({
                'success': True,
                'message': success_message,
                'log': get_log_messages()
            })
            
        except Exception as e:
            error_message = str(e)
            logger.error(f'Ошибка при загрузке фотографий: {error_message}')
            return jsonify({
                'error': error_message,
                'success': False,
                'log': get_log_messages()
            }), 500
            
    except Exception as e:
        error_message = f'Неожиданная ошибка: {str(e)}'
        logger.error(error_message)
        return jsonify({
            'error': error_message,
            'success': False,
            'log': get_log_messages()
        }), 500

def get_log_messages():
    """
    Получение последних сообщений из лог-файла.
    Возвращает последние 10 строк лога.
    """
    try:
        if not os.path.exists('app.log'):
            return ['Лог-файл не найден']
            
        with open('app.log', 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()[-10:]
            return [line.strip() for line in lines if line.strip()]
    except Exception as e:
        logger.error(f'Ошибка при чтении лога: {str(e)}')
        return ['Ошибка при чтении лога']

def get_vk_photos(user_id, vk_token):
    """
    Получение фотографий из профиля VK.
    
    Args:
        user_id (str): ID пользователя VK
        vk_token (str): Токен доступа VK API
        
    Returns:
        list: Список фотографий с информацией о них
        
    Raises:
        Exception: При ошибках доступа к API или неверных данных
    """
    logger.info(f'Получение фотографий пользователя {user_id}')
    url = f'https://api.vk.com/method/photos.get'
    params = {
        'owner_id': user_id,
        'album_id': 'profile',
        'extended': 1,
        'access_token': vk_token,
        'v': VK_API_VERSION,
        'rev': 1,
        'count': 100
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'error' in data:
            error_code = data['error'].get('error_code', 0)
            error_msg = data['error'].get('error_msg', 'Неизвестная ошибка')
            logger.error(f'Ошибка VK API (код {error_code}): {error_msg}')
            
            if error_code == 30:  # This profile is private
                raise Exception(
                    'Профиль пользователя является приватным.\n'
                    'Для решения проблемы:\n'
                    '1. Убедитесь, что вы ввели правильный ID пользователя\n'
                    '2. Проверьте, что профиль пользователя открыт\n'
                    '3. Если профиль закрыт, вы должны быть другом пользователя\n'
                    '4. Проверьте, что токен имеет права на чтение фотографий\n'
                    '5. Попробуйте использовать свой собственный ID пользователя'
                )
            elif error_code == 5:  # Authorization failed
                raise Exception('Ошибка авторизации VK. Проверьте правильность токена.')
            elif error_code == 113:  # Invalid user id
                raise Exception('Неверный ID пользователя VK. Проверьте правильность введенного ID.')
            else:
                raise Exception(f'Ошибка VK API: {error_msg}')
        
        if 'response' not in data:
            logger.error(f'Неожиданный ответ от VK API: {data}')
            raise Exception(f'Неожиданный ответ от VK API: {data}')
        
        photos = data['response']['items']
        if not photos:
            raise Exception('У пользователя нет фотографий в профиле')
            
        logger.info(f'Получено {len(photos)} фотографий')
        return photos
        
    except requests.exceptions.RequestException as e:
        logger.error(f'Ошибка при запросе к VK API: {str(e)}')
        raise Exception(f'Ошибка при запросе к VK API: {str(e)}')
    except json.JSONDecodeError as e:
        logger.error(f'Ошибка при разборе ответа VK API: {str(e)}')
        raise Exception('Ошибка при получении данных от VK API')

def upload_to_yandex_disk(file_name, file_path, yandex_token, folder_path=None):
    """
    Загрузка файла на Яндекс.Диск.
    
    Args:
        file_name (str): Имя файла для загрузки
        file_path (str): Путь к локальному файлу
        yandex_token (str): Токен доступа Яндекс.Диска
        folder_path (str, optional): Путь к папке на Яндекс.Диске
        
    Returns:
        str: URL загруженного файла
        
    Raises:
        Exception: При ошибках загрузки или неверном токене
    """
    logger.info(f'Загрузка файла {file_name} на Яндекс.Диск')
    headers = {
        'Authorization': f'OAuth {yandex_token}'
    }
    
    full_path = f"{folder_path}/{file_name}" if folder_path else file_name
    
    params = {
        'path': full_path,
        'overwrite': 'true'
    }
    
    # Проверка токена Яндекс.Диска
    check_url = 'https://cloud-api.yandex.net/v1/disk'
    check_response = requests.get(check_url, headers=headers)
    if check_response.status_code != 200:
        logger.error('Ошибка токена Яндекс.Диска')
        raise Exception('Ошибка токена Яндекс.Диска. Проверьте правильность токена.')
    
    # Создание папки, если указана
    if folder_path:
        logger.info(f'Создание папки {folder_path} на Яндекс.Диске')
        create_folder_url = 'https://cloud-api.yandex.net/v1/disk/resources'
        create_folder_params = {
            'path': folder_path
        }
        try:
            requests.put(create_folder_url, headers=headers, params=create_folder_params)
            logger.info(f'Папка {folder_path} успешно создана')
        except requests.exceptions.HTTPError:
            logger.info(f'Папка {folder_path} уже существует')
    
    # Получение URL для загрузки
    response = requests.get(YANDEX_DISK_UPLOAD_URL, headers=headers, params=params)
    response.raise_for_status()
    upload_url = response.json()['href']
    
    # Загрузка файла
    with open(file_path, 'rb') as f:
        upload_response = requests.put(upload_url, files={'file': f})
        upload_response.raise_for_status()
    
    logger.info(f'Файл {file_name} успешно загружен')
    return f'https://disk.yandex.ru/client/disk/{full_path}'

def upload_photos_to_yandex_disk(user_id, vk_token, yandex_token, folder_path=None):
    """
    Основная функция загрузки фотографий.
    
    Args:
        user_id (str): ID пользователя VK
        vk_token (str): Токен доступа VK API
        yandex_token (str): Токен доступа Яндекс.Диска
        folder_path (str, optional): Путь к папке на Яндекс.Диске
        
    Returns:
        list: Информация о загруженных фотографиях
    """
    # Получение и сортировка фотографий
    photos = get_vk_photos(user_id, vk_token)
    num_photos = 5
    photos = sorted(photos, key=lambda x: (-x['likes']['count'], x['date']))[:num_photos]

    # Создание локальной папки для временного хранения
    if not os.path.exists('vk_photos'):
        os.makedirs('vk_photos')
        logger.info('Создана локальная папка vk_photos')

    uploaded_photos_info = []

    # Загрузка каждой фотографии
    for i, photo in enumerate(photos, 1):
        logger.info(f'Обработка фотографии {i} из {len(photos)}')
        max_size = max(photo['sizes'], key=lambda x: x['width'] * x['height'])
        file_name = f"{photo['likes']['count']}.jpg"
        file_path = f"vk_photos/{file_name}"

        # Скачивание фотографии
        photo_url = max_size['url']
        photo_response = requests.get(photo_url)
        photo_response.raise_for_status()

        with open(file_path, 'wb') as f:
            f.write(photo_response.content)
        logger.info(f'Фотография {file_name} сохранена локально')

        # Загрузка на Яндекс.Диск
        yandex_url = upload_to_yandex_disk(file_name, file_path, yandex_token, folder_path)
        uploaded_photos_info.append({
            "file_name": file_name,
            "size": max_size['type'],
            "url": yandex_url
        })

    # Сохранение информации о загруженных фотографиях
    with open('uploaded_photos.json', 'w') as json_file:
        json.dump(uploaded_photos_info, json_file, indent=4)
    logger.info('Информация о загруженных фотографиях сохранена в uploaded_photos.json')

    return uploaded_photos_info

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080, debug=True)
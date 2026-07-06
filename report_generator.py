from jinja2 import Template
from datetime import datetime
from typing import List, Dict

def generate_html_report(scan_result: dict) -> str:
    """Генерация HTML отчёта по сканированию"""
    
    template = Template('''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Отчёт по скану - {{ article }}</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }
        
        .article {
            font-size: 16px;
            opacity: 0.9;
            font-family: 'Courier New', monospace;
            background: rgba(255,255,255,0.2);
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            margin-top: 10px;
        }
        
        .product-name {
            font-size: 20px;
            margin-top: 15px;
            font-weight: 500;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            padding: 30px;
            background: #f8f9fa;
        }
        
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }
        
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 5px;
        }
        
        .stat-label {
            font-size: 13px;
            color: #6c757d;
        }
        
        .content {
            padding: 30px;
        }
        
        .section-title {
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 20px;
            color: #333;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .stores-list {
            display: grid;
            gap: 15px;
        }
        
        .store-item {
            background: #f8f9fa;
            border-radius: 12px;
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: transform 0.2s;
        }
        
        .store-item:hover {
            transform: translateX(5px);
        }
        
        .store-info {
            flex: 1;
        }
        
        .store-name {
            font-weight: 600;
            color: #333;
            margin-bottom: 5px;
            font-size: 16px;
        }
        
        .store-address {
            font-size: 14px;
            color: #6c757d;
            margin-bottom: 5px;
        }
        
        .store-distance {
            font-size: 13px;
            color: #667eea;
            font-weight: 500;
        }
        
        .store-status {
            text-align: right;
            min-width: 120px;
        }
        
        .in-stock {
            color: #28a745;
            font-weight: 600;
            font-size: 15px;
            margin-bottom: 5px;
        }
        
        .no-stock {
            color: #dc3545;
            font-weight: 600;
            font-size: 15px;
            margin-bottom: 5px;
        }
        
        .price {
            font-size: 22px;
            font-weight: bold;
            color: #ffc107;
            text-shadow: 0 1px 2px rgba(0,0,0,0.1);
        }
        
        .nearest-store {
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
            padding: 25px;
            border-radius: 12px;
            margin-bottom: 30px;
        }
        
        .nearest-store h3 {
            margin-bottom: 10px;
            font-size: 18px;
        }
        
        .nearest-store .address {
            opacity: 0.95;
            margin-bottom: 5px;
        }
        
        .nearest-store .distance {
            opacity: 0.9;
            font-size: 14px;
        }
        
        .timestamp {
            text-align: center;
            padding: 20px;
            color: #6c757d;
            font-size: 13px;
            border-top: 1px solid #e9ecef;
        }
        
        .badge {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 10px;
        }
        
        .badge-adult {
            background: #ffc107;
            color: #000;
        }
        
        @media print {
            body {
                background: white;
                padding: 0;
            }
            .container {
                box-shadow: none;
            }
        }
        
        @media (max-width: 600px) {
            .stats {
                grid-template-columns: repeat(2, 1fr);
            }
            .store-item {
                flex-direction: column;
                align-items: flex-start;
                gap: 15px;
            }
            .store-status {
                text-align: left;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Отчёт по сканированию</h1>
            <div class="article">Артикул: {{ article }}</div>
            <div class="product-name">{{ title }}</div>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{{ stores_checked }}</div>
                <div class="stat-label">Проверено магазинов</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stores_in_stock }}</div>
                <div class="stat-label">В наличии</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ min_price }} ₽</div>
                <div class="stat-label">Мин. цена</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ radius }} м</div>
                <div class="stat-label">Радиус поиска</div>
            </div>
        </div>
        
        <div class="content">
            {% if nearest %}
            <div class="nearest-store">
                <h3>🎯 Ближайший магазин с товаром</h3>
                <div class="address">{{ nearest.store.name }}</div>
                <div class="address">{{ nearest.store.address }}</div>
                <div class="distance">📍 {{ "%.0f"|format(nearest.store.distance) }} м от вас</div>
                <div class="distance">💰 {{ nearest.price }} ₽</div>
            </div>
            {% endif %}
            
            <h2 class="section-title">📋 Все магазины</h2>
            <div class="stores-list">
                {% for result in all_results %}
                <div class="store-item">
                    <div class="store-info">
                        <div class="store-name">
                            🏪 {{ result.store.name }}
                            {% if result.is_adult %}
                            <span class="badge badge-adult">18+</span>
                            {% endif %}
                        </div>
                        <div class="store-address">📍 {{ result.store.address }}</div>
                        <div class="store-distance">📏 {{ "%.0f"|format(result.store.distance) }} м</div>
                    </div>
                    <div class="store-status">
                        {% if result.in_stock %}
                        <div class="in-stock">✓ В наличии</div>
                        <div class="price">{{ result.price }} ₽</div>
                        <div style="font-size: 12px; color: #6c757d;">{{ result.quantity }} шт.</div>
                        {% else %}
                        <div class="no-stock">✗ Нет в наличии</div>
                        <div style="font-size: 12px; color: #6c757d;">—</div>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        
        <div class="timestamp">
            Отчёт сформирован: {{ timestamp }}<br>
            Сгенерировано ботом @MagnitScannerBot
        </div>
    </div>
</body>
</html>
    ''')
    
    html = template.render(
        article=scan_result.get('article', ''),
        title=scan_result.get('title', ''),
        stores_checked=scan_result.get('stores_checked', 0),
        stores_in_stock=scan_result.get('stores_in_stock', 0),
        min_price=scan_result.get('min_price', 0),
        radius=scan_result.get('radius', 3000),
        nearest=scan_result.get('nearest'),
        all_results=scan_result.get('all_results', []),
        timestamp=datetime.now().strftime('%d.%m.%Y %H:%M:%S')
    )
    
    return html


def generate_simple_report(product: dict) -> str:
    """Генерация простого текстового отчёта"""
    text = (
        f"📦 *{product.get('name', 'Товар')}*\n\n"
        f"🔢 Артикул: `{product.get('id', '')}`\n"
        f"💰 Цена: {product.get('price', 0):.2f} ₽\n"
        f"📊 В наличии: {product.get('quantity', 0)} шт.\n"
        f"⭐ Рейтинг: {product.get('rating', 0)}/5\n"
        f"🏪 Магазин: {product.get('store_code', '')}\n\n"
        f"🔗 [Открыть на сайте]({product.get('url', '')})"
    )
    return text
import os
import sqlite3
import urllib.request
import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.express as px

# ==========================================
# INICIALIZACIÓN DE ESTADOS DE SESIÓN
# ==========================================
if 'analizado' not in st.session_state:
    st.session_state['analizado'] = False
if 'resultado' not in st.session_state:
    st.session_state['resultado'] = None
if 'idioma' not in st.session_state:
    st.session_state.idioma = 'ES'  # Español por defecto

# ==========================================
# FUNCIÓN DE TRADUCCIÓN
# ==========================================
def t(texto_es: str, texto_eu: str) -> str:
    """Función simple para cambiar entre Español y Euskera"""
    return texto_es if st.session_state.idioma == 'ES' else texto_eu

# ==========================================
# CONFIGURACIÓN DE BASE DE DATOS
# ==========================================
DB_PATH = "gestion_coleccion.db"
DB_URL = "https://www.dropbox.com/scl/fi/zlhw2qkfpebtvzaimxto1/bibliotecas_navarra2.db?rlkey=fg46liauy6omsq3dkz4gnn5pk&st=jr3xe9k4&dl=1"

def asegurar_base_de_datos():
    """Maneja la descarga del archivo en disco."""
    debe_descargar = False
   
    if not os.path.exists(DB_PATH):
        debe_descargar = True
    elif os.path.getsize(DB_PATH) < 10000:
        os.remove(DB_PATH)
        debe_descargar = True

    if debe_descargar:
        with st.spinner(t(
            "Descargando base de datos de la colección (500MB)... Esto puede tardar un minuto la primera vez.",
            "Bildumaren datu-basea deskargatzen (500MB)... Lehen aldiz minutu bat iraun dezake."
        )):
            try:
                urllib.request.urlretrieve(DB_URL, DB_PATH)
                st.toast(t("¡Base de datos descargada con éxito!", "Datu-basea ondo deskargatu da!"), icon="📥")
                return True
            except Exception as e:
                st.error(t(
                    f"Error crítico al descargar la base de datos desde Dropbox: {e}",
                    f"Errore kritikoa datu-basea Dropbox-etik deskargatzean: {e}"
                ))
                return False
    return True

# ==========================================
# EJECUCIÓN DE LA VERIFICACIÓN
# ==========================================
if asegurar_base_de_datos():
    conn = sqlite3.connect(DB_PATH)
else:
    conn = None
    st.error(t(
        "No se pudo establecer la conexión porque falló la preparación del archivo .db",
        "Ezin izan da konexioa ezarri .db fitxategiaren prestaketa huts egin duelako"
    ))

@st.cache_resource
def obtener_conexion_db():
    """Únicamente se encarga de cachear el recurso de conexión."""
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        return conn
    except Exception as e:
        return None

# Inicializar la lógica de manera secuencial y segura
if asegurar_base_de_datos():
    conn = obtener_conexion_db()
    if conn is None:
        st.error(t("Error al conectar con el archivo SQLite.", "Errorea SQLite fitxategiarekin konektatzean."))
else:
    conn = None

# ==========================================
# FUNCIONES AUXILIARES DE RECOMENDACIÓN
# ==========================================
def obtener_recomendaciones_automaticas(conexion, bibliotecas, limite=50):
    if isinstance(bibliotecas, str):
        bibliotecas = [bibliotecas]
    elif not isinstance(bibliotecas, (list, tuple)):
        st.error(t(
            f"❌ 'bibliotecas' debe ser texto o lista. Recibí: {type(bibliotecas)}",
            f"❌ 'bibliotecas' testua edo zerrenda izan behar du. Jasota: {type(bibliotecas)}"
        ))
        return pd.DataFrame()
  
    if not bibliotecas:
        st.error(t("❌ Debes indicar al menos una biblioteca.", "❌ Gutxienez liburutegi bat adierazi behar duzu."))
        return pd.DataFrame()
  
    placeholders = ','.join(['?'] * len(bibliotecas))
  
    query = f"""
        SELECT
            l.id_sistema,
            l.titulo,
            l.autor,
            l.anio,
            COUNT(DISTINCT e.biblioteca) as total_bibliotecas
        FROM libros l
        JOIN ejemplares e ON l.id_sistema = e.id_sistema
        WHERE l.id_sistema NOT IN (
            SELECT DISTINCT id_sistema
            FROM ejemplares
            WHERE TRIM(UPPER(biblioteca)) IN ({placeholders})
        )
        GROUP BY l.id_sistema, l.titulo, l.autor, l.anio
        ORDER BY total_bibliotecas DESC
        LIMIT ?
    """
    try:
        params = [b.upper().strip() for b in bibliotecas] + [int(limite)]
        df = pd.read_sql_query(query, conexion, params=params)
        return df
    except Exception as e:
        st.error(t(f"❌ Error en la consulta SQL: {str(e)}", f"❌ SQL kontsultan errorea: {str(e)}"))
        return pd.DataFrame()

def obtener_recomendaciones_por_materia_avanzada(conexion, biblioteca, patron_regex, anios, min_ejemplares, limite):
    """
    Extrae recomendaciones utilizando expresiones regulares directas en SQLite.
    """
    anio_actual = 2026
    anio_corte = anio_actual - anios
    try:
        conexion.create_function(
            "REGEXP",
            2,
            lambda expr, item: bool(re.search(expr, str(item), re.IGNORECASE)) if item else False
        )
       
        query = """
            SELECT
                c.id_sistema, c.titulo, c.autor, c.editorial, c.anio, c.cdu,
                c.isbn, c.materias, c.ejemplares, c.bibliotecas
            FROM catalogo c
            WHERE c.anio >= ?
              AND c.ejemplares >= ?
              AND c.id_sistema IN (
                  SELECT id_sistema FROM materias WHERE materia REGEXP ?
              )
              AND c.id_sistema NOT IN (
                  SELECT id_sistema FROM inventario_centros WHERE codigo_biblioteca = ?
              )
            ORDER BY c.ejemplares DESC
            LIMIT ?
        """
       
        parametros = (anio_corte, min_ejemplares, patron_regex, biblioteca, limite)
        df_resultado = pd.read_sql_query(query, conexion, params=parametros)
        return df_resultado
       
    except Exception as e:
        print(f"Error en la consulta analítica por materias: {e}")
        return pd.DataFrame()

# ==========================================
# BACKEND Y FUNCIÓN DE PROCESAMIENTO
# ==========================================
BIBLIOTECAS = {
    "Ablitas": 2610, "Aibar / Oibar": 769, "Allo": 988, "Altsasu / Alsasua": 7590, "Andosilla": 2882,
    "Ansoáin / Antsoain": 10608, "Añorbe": 628, "Aoiz, Agoitz": 2970, "Aranguren": 12517, "Arbizu": 1126,
    "Arguedas": 2313, "Arroniz": 1035, "Artajona": 1772, "Artica / Artika": 4848, "Aurizberri / Espinal": 2627,
    "Ayegui, Aiegi": 2531, "Azagra": 3749, "Barañain": 19575, "Baztan": 7831, "Bera": 3792, "Beriáin": 4129,
    "Berriozar": 10919, "Bibliobús": 8700, "Buñuel": 2309, "Burlada / Burlata": 20865, "Cabanillas": 1379,
    "Cadreita": 2186, "Caparroso": 2786, "Cárcar": 1150, "Carcastillo": 2435, "Cascante": 4050, "Cáseda": 969,
    "Castejón": 4435, "Cintruénigo": 8265, "Cirauqui / Zirauki": 467, "Corella": 8629, "Cortes": 3149,
    "Doneztebe / Santesteban": 1858, "Valle de Egües / Egusibar": 22121, "Estella / Lizarra": 14195,
    "Etxarri Aranatz": 2521, "Falces": 2375, "Fitero": 2146, "Fontellas": 1005, "Funes": 2542, "Fustiñana": 2457,
    "Huarte / Uharte": 7562, "Irurtzun": 2316, "Larraga": 2087, "Leitza": 3016, "Lekunberri": 1689,
    "Lerín": 1789, "Lesaka": 2731, "Lodosa": 4894, "Los Arcos": 1151, "Lumbier": 1326, "Mañeru": 445,
    "Marcilla": 2875, "Mélida": 715, "Mendavia": 3496, "Mendigorria": 1191, "Milagro": 3549,
    "Miranda de Arga": 917, "Monteagudo": 1102, "Murchante": 4237, "Noain": 8429, "Obanos": 920,
    "Olazti / Olaztigutía": 1483, "Olite / Erriberri": 4019, "Orkoien": 4051, "Oteiza": 923,
    "Peralta / Azkoien": 5979, "PNA - Biblioteca de Navarra": 208243, "PNA - Civican": 19418,
    "PNA - Echavacoiz": 5447, "PNA - Iturrama": 22354, "PNA - Mendillorri": 18747, "PNA - Milagrosa": 34998,
    "PNA - San Francisco": 25864, "PNA - San Jorge": 22203, "PNA - San Pedro": 26896, "PNA - Txantrea": 20264,
    "PNA - Yamaguchi": 16372, "Puente la Reina / Gares": 2944, "Ribaforada": 3715, "Roncal / Erronkari": 209,
    "San Adrián": 6429, "Sangüesa / Zangoza": 4814, "Sartaguda": 1328, "Sesma": 1226, "Tafalla": 10698,
    "Tudela": 37791, "Ultzama": 1636, "Urdiain": 638, "Valtierra": 2423, "Viana": 4370, "Villafranca": 3004,
    "Villava / Atarrabia": 10067, "Ziorda": 352, "Zizur Mayor / Zizur Nagusia": 15715
}

@st.cache_data
def procesar_datos(topo_bytes, nunca_bytes, mas2_bytes, catalogo_bytes, tipo_analisis, num_caracteres):
    if not topo_bytes or not catalogo_bytes:
        return None, 0
  
    topo_text = topo_bytes.decode('utf-8', errors='replace')
    data = []
    for line in topo_text.split('\n'):
        line = line.strip()
        if not line or re.search(r'^(\d{2}/\d{2}/\d{4}|LISTADO|Signatura|-----)', line):
            continue
      
        match = re.search(r'\b(\d{7,})\b', line)
        if not match:
            continue
        record_id = int(match.group(1))
      
        sign_match = re.search(r'(.+?)\s+84\s+[A-Z]{2}', line)
        signatura = sign_match.group(1).strip() if sign_match else line
      
        title_match = re.search(r'\d{7,}\s+(.{10,})', line)
        title = title_match.group(1).strip() if title_match else t("Título no detectado", "Izenburua ez da detektatu")
      
        data.append({
            "record_id": record_id,
            "signatura_real": signatura,
            "titulo": title
        })

    df_topo = pd.DataFrame(data).drop_duplicates(subset=['record_id'])
    if df_topo.empty:
        return None, 0

    cat_text = catalogo_bytes.decode('utf-8', errors='replace')
    cat_text = re.sub(r'\b\d{2}/\d{2}/\d{4}\b', '', cat_text)
  
    year_dict = {}
    matches = list(re.finditer(r'\b\d{7,}\b', cat_text))
    for i, m in enumerate(matches):
        rid = int(m.group())
        start = m.start()
        end = matches[i+1].start() if i < len(matches)-1 else len(cat_text)
        block = cat_text[start:end]
        years = re.findall(r'\b(18\d{2}|19\d{2}|20\d{2})\b', block)
        years = [int(y) for y in years if 1800 <= int(y) <= 2026]
        if years:
            year_dict[rid] = max(years)

    df_final = df_topo[df_topo['record_id'].isin(year_dict.keys())].copy()
    df_final['year'] = df_final['record_id'].map(year_dict)

    df_final['prestamos'] = 1
    if nunca_bytes:
        nunca_text = nunca_bytes.decode('utf-8', errors='replace')
        nunca_ids = {int(x) for x in re.findall(r'\b\d{7,}\b', nunca_text)}
        df_final.loc[df_final['record_id'].isin(nunca_ids), 'prestamos'] = 0
    if mas2_bytes:
        mas2_text = mas2_bytes.decode('utf-8', errors='replace')
        mas2_ids = {int(x) for x in re.findall(r'\b\d{7,}\b', mas2_text)}
        df_final.loc[df_final['record_id'].isin(mas2_ids), 'prestamos'] = 2

    df_final['prestado'] = df_final['prestamos'] > 0

    # (La función clasificar_dinamico se mantiene igual porque genera texto interno de categorías)
    def clasificar_dinamico(sign):
        if not sign or not isinstance(sign, str):
            return "Sin clasificar"
        s = sign.strip().upper()
      
        if tipo_analisis == "Clasificación Mixta Estándar (CDU + Letras)":
            if re.search(r'\bI\s+DVD\b', s): return "I DVD (DVD Infantil)"
            if re.search(r'\bDVD\b', s): return "DVD Audiovisual"
            if re.search(r'^IC\b', s): return "IC (Comic Infantil)"
            if re.search(r'^C\b', s): return "C (Comic Adultos)"
            if re.search(r'\bIP\b', s): return "IP (Infantil Poesía)"
            if re.search(r'\bIT\b', s): return "IT (Infantil Teatro)"
            if re.search(r'^I\s+[12356789]', s): return "CDU Infantil"
          
            match_inf = re.match(r'^(I[0-3])', s)
            if match_inf: return f"{match_inf.group(1)} (Infantil)"
          
            if re.search(r'\bJN\b', s): return "JN (Juvenil)"
            if re.search(r'\bN\s', s): return "Ficción / Narrativa"
            if re.search(r'\bP\s', s): return "Poesía"
            if re.search(r'\bT\s', s): return "Teatro"
          
            m = re.match(r'^(\d)', s)
            if m:
                cats = {
                    '0':'0 - Generalidades', '1':'1 - Filosofía', '2':'2 - Religión',
                    '3':'3 - Ciencias Sociales', '4':'4 - Lingüística',
                    '5':'5 - Ciencias Puras', '6':'6 - Tecnología',
                    '7':'7 - Arte / Deportes', '8':'8 - Literatura',
                    '9':'9 - Historia / Geografía'
                }
                return cats.get(m.group(1), f"CDU {m.group(1)}xx")
            return "Otros"
          
        elif tipo_analisis == "Solo Dígitos Iniciales de la CDU":
            m = re.match(r'^(\d+)', s)
            return f"CDU {m.group(1)[0]}" if m else "Ficción / Otros"
          
        elif tipo_analisis == "Longitud Fija (Primeros caracteres)":
            return s[:num_caracteres]
      
        return "Otros"

    df_final['categoria'] = df_final['signatura_real'].apply(clasificar_dinamico)
    return df_final, (len(df_topo) - len(df_final))

    # ==========================================
# ESTILOS E INTERFAZ BASE
# ==========================================
st.markdown("""
    <style>
    .main-title { font-size: 2.3rem; color: #1E3A8A; font-weight: bold; margin-bottom: 0.3rem; }
    .subtitle { font-size: 1.1rem; color: #4B5563; margin-bottom: 2rem; }
    div[data-testid="metric-container"] {
        background-color: #F3F4F6; border-radius: 0.5rem; padding: 1rem; box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    </style>
""", unsafe_allow_html=True)

st.markdown(f'<div class="main-title">📚 {t("Gestión de la colección", "Bildumaren kudeaketa")}</div>', unsafe_allow_html=True)
st.markdown(f'<div class="subtitle">{t("Herramienta para ayudarte a conocer un poco mejor la colección de tu biblioteca", "Zure liburutegiko bilduma hobeto ezagutzen laguntzeko tresna")}</div>', unsafe_allow_html=True)

# ==========================================
# PANEL LATERAL (SIDEBAR)
# ==========================================
with st.sidebar:
    # Selector de Idioma
    st.title("🌍 Idioma / Hizkuntza")
    idioma_seleccionado = st.radio(
        "Selecciona / Aukeratu:",
        ['ES', 'EU'],
        index=0 if st.session_state.idioma == 'ES' else 1,
        horizontal=True
    )
    if idioma_seleccionado != st.session_state.idioma:
        st.session_state.idioma = idioma_seleccionado
        st.rerun()

    st.header(t("🏢 1. Selección de Biblioteca", "🏢 1. Liburutegiaren Hautaketa"))
    biblioteca_seleccionada = st.selectbox(
        t("Biblioteca:", "Liburutegia:"), 
        options=list(BIBLIOTECAS.keys())
    )
    poblacion_atendida = BIBLIOTECAS[biblioteca_seleccionada]

    st.markdown("---")

    if not st.session_state['analizado']:
        st.header(t("📂 2. Carga de Archivos", "📂 2. Fitxategiak Kargatu"))
        uploaded_topo = st.file_uploader(
            t("Archivo Topográfico (.txt) *Requerido*", "Topografiko Fitxategia (.txt) *Beharrezkoa*"), 
            type=["txt"]
        )
        uploaded_catalogo = st.file_uploader(
            t("Catálogo Completo (.txt) *Requerido*", "Katalogo Osoa (.txt) *Beharrezkoa*"), 
            type=["txt"]
        )
        uploaded_nunca = st.file_uploader(
            t("No Prestados (.txt)", "Ez mailegatuak (.txt)"), 
            type=["txt"]
        )
        uploaded_mas2 = st.file_uploader(
            t("Más Prestados (.txt)", "Gehien mailegatuak (.txt)"), 
            type=["txt"]
        )

        st.markdown("---")
       
        # Variables fijas
        tipo_analisis = "Clasificación Mixta Estándar (CDU + Letras)"
        num_caracteres = 3
      
        if st.button(t("🚀 Analizar Fondos", "🚀 Bilduma Analizatu"), type="primary", use_container_width=True):
            if not uploaded_topo or not uploaded_catalogo:
                st.error(t("⚠️ Sube los archivos requeridos.", "⚠️ Beharrezko fitxategiak igo."))
            else:
                with st.spinner(t("Procesando datos...", "Datuak prozesatzen...")):
                    resultado = procesar_datos(
                        uploaded_topo.getvalue(),
                        uploaded_nunca.getvalue() if uploaded_nunca else None,
                        uploaded_mas2.getvalue() if uploaded_mas2 else None,
                        uploaded_catalogo.getvalue(),
                        tipo_analisis,
                        num_caracteres
                    )
                    if resultado is not None:
                        st.session_state['resultado'] = resultado
                        st.session_state['analizado'] = True
                        st.session_state['tipo_analisis'] = tipo_analisis
                        st.rerun()
    else:
        st.success(t("✅ Datos cargados en memoria.", "✅ Datuak memoriara kargatu dira."))
        if st.button(t("🔄 Cambiar / Volver a subir archivos", "🔄 Aldatu / Fitxategiak berriro igo"), use_container_width=True):
            st.session_state['analizado'] = False
            st.session_state['resultado'] = None
            st.rerun()

# ==========================================
# PANEL CENTRAL: ESTRUCTURA MAESTRA DE DOS CATEGORÍAS
# ==========================================
if st.session_state['analizado'] and st.session_state['resultado'] is not None:
    df_completo, huerfanos = st.session_state['resultado']
  
    total_docs = len(df_completo)
    pct_prestados = (df_completo['prestado'].sum() / total_docs * 100) if total_docs > 0 else 0
    edad_media = df_completo['year'].mean()
    docs_por_habitante = total_docs / poblacion_atendida if poblacion_atendida > 0 else 0

    # Indicadores globales superiores
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(t("📖 Total Volúmenes", "📖 Bolumen Totala"), f"{total_docs:,}")
    m2.metric(t("🪪 Índice de Circulación", "🪪 Zirkulazio Indizea"), f"{pct_prestados:.1f}%")
    m3.metric(
        t("📅 Edad Media del Fondo", "📅 Bildumaren Batez besteko Adina"), 
        f"{int(edad_media)}" if not np.isnan(edad_media) else "N/A"
    )
    m4.metric(t("👥 Docs por Habitante", "👥 Biztanleko Dokumentuak"), f"{docs_por_habitante:.2f}")
  
    if huerfanos > 0:
        st.caption(t(
            f"ℹ️ Se han omitido {huerfanos} registros del topográfico por incoherencias con el catálogo.",
            f"ℹ️ {huerfanos} erregistro omisitu dira topografikotik katalogoarekin koherentziarik ez dutelako."
        ))

    st.markdown("---")

    # LAS DOS GRANDES CATEGORÍAS SOLICITADAS
    pestana_analisis, pestana_compras = st.tabs([
        t("📊 1. Análisis de la Colección", "📊 1. Bildumaren Analisia"),
        t("🎯 2. Recomendaciones de Compra", "🎯 2. Erosketa Gomendioak")
    ])




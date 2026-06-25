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
    
            # ==========================================
        # BLOQUE 1: ANÁLISIS DE LA COLECCIÓN
        # ==========================================
        with pestana_analisis:
            subtab_general, subtab_cdu, subtab_signatura = st.tabs([
                t("📈 A) Análisis General", "📈 A) Analisi Orokorra"),
                t("🗂️ B) Análisis por CDU", "🗂️ B) CDU arabera Analisia"),
                t("🔎 C) Análisis Profundo por Signatura", "🔎 C) Signatura arabera Analisi Sakona")
            ])
           
            # A) ANÁLISIS GENERAL
            with subtab_general:
                st.subheader(t("⚖️ Diagnóstico según Pautas Oficiales (IFLA)", "⚖️ IFLAren arauen arabera diagnostikoa"))
              
                # 1. Matriz completa de pautas oficiales según tramos de población
                if poblacion_atendida <= 5000:
                    pauta_hab, pauta_min, pauta_max = 2.5, 4000, 5500
                elif poblacion_atendida <= 10000:
                    pauta_hab, pauta_min, pauta_max = 2.5, 7000, 12500
                elif poblacion_atendida <= 20000:
                    pauta_hab, pauta_min, pauta_max = 2.0, 12500, 20000
                elif poblacion_atendida <= 50000:
                    pauta_hab, pauta_min, pauta_max = 2.0, 20000, 65000
                elif poblacion_atendida <= 100000:
                    pauta_hab, pauta_min, pauta_max = 1.5, 45000, 80000
                else:
                    pauta_hab, pauta_min, pauta_max = 1.5, 80000, 95000
    
                col_al1, col_al2 = st.columns(2)
                with col_al1:
                    # Diagnóstico por volumen bruto total
                    if total_docs < 2500:
                        st.error(t(
                            f"🚨 **Alerta:** Suelo mínimo absoluto IFLA es de 2.500 obras. Tienes **{total_docs:,}**.",
                            f"🚨 **Alerta:** IFLAren gutxieneko zorua 2.500 obra da. **{total_docs:,}** dituzu."
                        ))
                    elif total_docs < pauta_min:
                        st.warning(t(
                            f"⚠️ **Déficit de fondo:** Recomendado para tu población: {pauta_min:,}-{pauta_max:,}. Tienes **{total_docs:,}** u.",
                            f"⚠️ **Fondo defizita:** Zure populazioarentzat gomendatua: {pauta_min:,}-{pauta_max:,}. **{total_docs:,}** dituzu."
                        ))
                    elif total_docs > pauta_max:
                        st.info(t(
                            f"ℹ️ **Fondo extenso:** El rango inicial recomendado es {pauta_min:,}-{pauta_max:,}. Tienes **{total_docs:,}** u.",
                            f"ℹ️ **Fondo zabala:** Gomendatutako hasierako tartea {pauta_min:,}-{pauta_max:,} da. **{total_docs:,}** dituzu."
                        ))
                    else:
                        st.success(t(
                            f"✅ **Óptimo:** Volumen bruto adecuado dentro del rango ({pauta_min:,}-{pauta_max:,}).",
                            f"✅ **Optimoa:** Bolumen gordina tarte egokian dago ({pauta_min:,}-{pauta_max:,})."
                        ))
    
                with col_al2:
                    # Diagnóstico corregido por ratio de habitante
                    if docs_por_habitante > 3.5:
                        st.warning(t(
                            f"⚠️ **Colección demasiado grande:** Tienes **{docs_por_habitante:.2f}** libros por persona (Límite óptimo: {pauta_hab} - Máx sugerido: 3.5).",
                            f"⚠️ **Bilduma handiegia:** Pertsonako **{docs_por_habitante:.2f}** liburu dituzu (Muga optimoa: {pauta_hab} - Gehenez 3.5)."
                        ))
                    elif docs_por_habitante < pauta_hab:
                        st.warning(t(
                            f"⚠️ **Ratio Bajo:** **{docs_por_habitante:.2f}** doc/hab. (Mínimo recomendado: {pauta_hab}).",
                            f"⚠️ **Ratio baxua:** **{docs_por_habitante:.2f}** dok./bizt. (Gomendatutako gutxienekoa: {pauta_hab})."
                        ))
                    else:
                        st.success(t(
                            f"✅ **Ratio Óptimo:** **{docs_por_habitante:.2f}** doc/hab.",
                            f"✅ **Ratio Optimoa:** **{docs_por_habitante:.2f}** dok./bizt."
                        ))
    
                st.write(t("#### 📊 Distribución Macroscópica", "#### 📊 Banaketa Makroskopikoa"))
               
                def clasificar_macro(cat):
                    c = str(cat).strip().upper()
                    if "DVD" in c or "AUDIOVISUAL" in c or "CD" in c:
                        return "Audiovisuales"
                    if re.match(r'^(I|JN|IC|IP|IT|INFANTIL|JUVENIL)(\s|\d+|-|$)', c):
                        return "Infantil/Juvenil"
                    return "Adultos"
    
                df_completo['macro_seccion'] = df_completo['categoria'].apply(clasificar_macro)
                macro_counts = df_completo['macro_seccion'].value_counts()
              
                p_adultos = (macro_counts.get("Adultos", 0) / total_docs * 100) if total_docs > 0 else 0
                p_infantil = (macro_counts.get("Infantil/Juvenil", 0) / total_docs * 100) if total_docs > 0 else 0
                p_audio = (macro_counts.get("Audiovisuales", 0) / total_docs * 100) if total_docs > 0 else 0
    
                tabla_macro = pd.DataFrame({
                    t("Sección", "Atala"): [t("Adultos", "Helduak"), t("Infantil/Juvenil", "Haur/Jubenil"), t("Audiovisuales", "Audiovisualak")],
                    t("Distribución", "Banaketa"): [f"{p_adultos:.1f}%", f"{p_infantil:.1f}%", f"{p_audio:.1f}%"]
                })
                st.dataframe(tabla_macro, use_container_width=True, hide_index=True)
    
                st.write(t("#### 📈 Nivel de Rotación Física", "#### 📈 Erabilera Fisikoaren Maila"))
                status_map = {0: t('Nunca prestado', 'Inoiz mailegatu gabe'), 
                             1: t('Prestado', 'Mailegatu'), 
                             2: t('Muy prestado', 'Oso mailegatu')}
                status_counts = df_completo['prestamos'].map(status_map).value_counts().reset_index()
                status_counts.columns = [t('Estado', 'Egoera'), t('Cantidad', 'Kopurua')]
                
                fig_pie = px.pie(status_counts, values='Cantidad', names='Estado', hole=0.4, color_discrete_sequence=px.colors.qualitative.Safe)
                st.plotly_chart(fig_pie, use_container_width=True)
    
                st.write(t("#### ⏳ Cronología de Ediciones", "#### ⏳ Edizioen Kronologia"))
                if not df_completo['year'].dropna().empty:
                    fig_hist = px.histogram(
                        df_completo, 
                        x='year', 
                        nbins=25, 
                        labels={'year': t('Año de Publicación', 'Argitalpen Urtea')}, 
                        color_discrete_sequence=['#1E3A8A']
                    )
                    st.plotly_chart(fig_hist, use_container_width=True)
    
            # B) ANÁLISIS POR CDU
            with subtab_cdu:
                st.subheader(t("🗂️ Concentración y Rendimiento por Secciones", "🗂️ Atalen Kontzentrazioa eta Errendimendua"))
              
                df_metrics = df_completo.groupby('categoria').agg(
                    Volúmenes=('record_id', 'count'),
                    Prestados=('prestado', 'sum'),
                    Año_Medio=('year', 'mean')
                ).reset_index()
              
                df_metrics[t('% Uso (Rotación)', '% Erabilera (Biraketa)')] = (df_metrics['Prestados'] / df_metrics['Volúmenes'] * 100).round(1)
                df_metrics[t('Año Medio Edición', 'Batez besteko Argitalpen Urtea')] = df_metrics['Año_Medio'].fillna(0).astype(int)
    
                # ... (mantengo las funciones es_categoria_infantil y segmentación igual)
    
                df_adultos = df_metrics[~df_metrics['es_infantil']].sort_values(by='Volúmenes', ascending=False)
                df_infantil = df_metrics[df_metrics['es_infantil']].sort_values(by='Volúmenes', ascending=False)
              
                st.markdown(t("### 👨‍💼 Análisis Sección Adultos", "### 👨‍💼 Helduen Atalaren Analisia"))
                if not df_adultos.empty:
                    fig_bar_adultos = px.bar(
                        df_adultos,
                        x='categoria',
                        y='Volúmenes',
                        color=t('% Uso (Rotación)', '% Erabilera (Biraketa)'),
                        title=t("Adultos: Volumen vs Rotación por Categoría", "Helduak: Bolumena vs Biraketa Kategoriaka"),
                        color_continuous_scale="Blues",
                        labels={'categoria': t('Categoría / CDU', 'Kategoria / CDU'), 'Volúmenes': t('Nº Volúmenes', 'Bolumen Kopurua')}
                    )
                    st.plotly_chart(fig_bar_adultos, use_container_width=True)
                  
                    st.dataframe(
                        df_adultos[['categoria', 'Volúmenes', t('% Uso (Rotación)', '% Erabilera (Biraketa)'), t('Año Medio Edición', 'Batez besteko Argitalpen Urtea')]],
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info(t("ℹ️ No hay datos suficientes para generar el análisis de Adultos.", "ℹ️ Ez dago datu nahikorik Helduen analisia sortzeko."))
    
                st.markdown("---")
               
                st.markdown(t("### 👶 Análisis Sección Infantil / Juvenil", "### 👶 Haur eta Jubenilen Atalaren Analisia"))
                if not df_infantil.empty:
                    fig_bar_infantil = px.bar(
                        df_infantil,
                        x='categoria',
                        y='Volúmenes',
                        color=t('% Uso (Rotación)', '% Erabilera (Biraketa)'),
                        title=t("Infantil/Juvenil: Volumen vs Rotación por Categoría", "Haur/Jubenil: Bolumena vs Biraketa Kategoriaka"),
                        color_continuous_scale="Purples",
                        labels={'categoria': t('Categoría / Tejuelo', 'Kategoria / Tejuelo'), 'Volúmenes': t('Nº Volúmenes', 'Bolumen Kopurua')}
                    )
                    st.plotly_chart(fig_bar_infantil, use_container_width=True)
                  
                    st.dataframe(
                        df_infantil[['categoria', 'Volúmenes', t('% Uso (Rotación)', '% Erabilera (Biraketa)'), t('Año Medio Edición', 'Batez besteko Argitalpen Urtea')]],
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info(t("ℹ️ No hay datos suficientes para generar el análisis Infantil.", "ℹ️ Ez dago datu nahikorik Haur analisia sortzeko."))
    
            # C) ANÁLISIS PROFUNDO POR SIGNATURA
            with subtab_signatura:
                st.subheader(t("🔎 Analiza la colección a través de las signaturas.", "🔎 Bilduma signaturen bidez aztertu."))
               
                def identificar_infantil(categoria):
                    cat_str = str(categoria).upper()
                    if "INFANTIL" in cat_str or "JUVENIL" in cat_str: return True
                    if re.match(r'^(I[0-9]?|JN|IC|IP|IT)(\s|$)', cat_str): return True
                    return False
    
                df_completo['es_infantil'] = df_completo['categoria'].apply(identificar_infantil)
    
                filtro_pub = st.radio(
                    t("1. Selecciona la Sección:", "1. Atala hautatu:"),
                    [t("📚 Todo el fondo", "📚 Bilduma osoa"), 
                     t("👨‍💼 Solo Adultos", "👨‍💼 Helduak soilik"), 
                     t("👶 Solo Infantil / Juvenil", "👶 Haur/Jubenil soilik")], 
                    horizontal=True
                )
              
                df_nivel1 = df_completo.copy()
                if "Adultos" in filtro_pub:
                    df_nivel1 = df_nivel1[~df_nivel1['es_infantil']]
                elif "Infantil" in filtro_pub:
                    df_nivel1 = df_nivel1[df_nivel1['es_infantil']]
    
                st.markdown("---")
    
                st.markdown(t("#### 🎯 Criterios de Selección y Búsqueda", "#### 🎯 Hautaketa eta Bilaketa Kriterioak"))
    
                col_busqueda, col_prestamos = st.columns([2, 1])
              
                with col_busqueda:
                    busqueda_sig = st.text_input(
                        t("⌨️ Buscar por Signatura / CDU (Soporta comodines como `*`):", "⌨️ Signatura / CDU bilatu ( `*` komodinoak onartzen ditu):"),
                        value="",
                        placeholder=t("Ej: *(460.16)* para Navarra, 821* para literatura...", "Adib: *(460.16)* Nafarroa, 821* literatura...")
                    ).strip().upper()
                  
                with col_prestamos:
                    filtro_pr = st.selectbox(
                        t("🪪 Historial Préstamos:", "🪪 Maileguen Historia:"),
                        [t("Todos", "Guztiak"), 
                         t("Nunca prestado (0)", "Inoiz mailegatu gabe (0)"), 
                         t("Préstamo Estándar (1)", "Mailegu Estandarra (1)"), 
                         t("Alta Demanda (2)", "Eskaera Handia (2)")]
                    )
    
                # ... (resto del código de filtros se mantiene igual, solo traduzco los textos visibles)
    
                st.markdown("---")
    
                st.markdown(f"**{t('Resultados encontrados', 'Aurkitutako emaitzak')}: {len(df_final_expurgo)} {t('documentos', 'dokumentu')}**")
              
                tabla_mostrar = df_final_expurgo[['record_id', 'signatura_real', 'titulo', 'year', 'categoria', 'prestamos']].copy()
                tabla_mostrar.columns = [
                    'id_sistema', 
                    t('Signatura', 'Signatura'), 
                    t('Título', 'Izenburua'), 
                    t('Año', 'Urtea'), 
                    t('Categoría', 'Kategoria'), 
                    t('Préstamos', 'Maileguak')
                ]
              
                st.dataframe(tabla_mostrar, use_container_width=True, hide_index=True)
    
                st.markdown(t("### 📊 Indicadores Globales de la Selección", "### 📊 Hautaketaren Adierazle Globalak"))
    
                if not df_final_expurgo.empty:
                    num_volumenes = len(df_final_expurgo)
                    libros_prestados = (df_final_expurgo['prestamos'] > 0).sum()
                    pct_prestados = round((libros_prestados / num_volumenes) * 100, 1)
                  
                    anios_validos = df_final_expurgo['year'].dropna()
                    anio_medio_col = int(anios_validos.mean()) if not anios_validos.empty else t("Sin datos de año", "Urte daturik ez")
    
                    df_resumen_kpi = pd.DataFrame([{
                        t("Número de volúmenes", "Bolumen kopurua"): f"{num_volumenes} ej.",
                        t("% de préstamos (Uso Activo)", "% mailegu (Erabilera Aktiboa)"): f"{pct_prestados} %",
                        t("Año medio de la colección", "Bildumaren batez besteko urtea"): anio_medio_col
                    }])
                  
                    st.dataframe(df_resumen_kpi, use_container_width=True, hide_index=True)
                else:
                    st.info(t("ℹ️ Modifica los criterios de búsqueda para calcular los indicadores del fondo.", "ℹ️ Bilaketa irizpideak aldatu fondoaren adierazleak kalkulatzeko."))
    
            # ==========================================
        # BLOQUE 2: RECOMENDACIONES DE COMPRA
        # ==========================================
        with pestana_compras:
            subtab_rec_gen, subtab_rec_cdu = st.tabs([
                t("🌐 A) Recomendaciones Generales", "🌐 A) Gomendio Orokorrak"),
                t("📚 B) Recomendaciones por CDU", "📚 B) CDU arabera Gomendioak")
            ])
           
            # A) RECOMENDACIONES GENERALES
            with subtab_rec_gen:
                st.subheader(t("📈 Títulos más Populares en la Red Ausentes en tu Centro", "📈 Sareko Titulu Popularesenak Zure Zentroan Ez Daudenak"))
                limite_gen = st.number_input(
                    t("Número de títulos a sugerir:", "Gomendatutako titulu kopurua:"), 
                    min_value=5, max_value=200, value=50, step=5
                )
               
                if conn is not None:
                    df_rec_gen = obtener_recomendaciones_automaticas(conn, biblioteca_seleccionada, limite_gen)
                    if not df_rec_gen.empty:
                        df_rec_gen.columns = [
                            "ID Sistema", 
                            t("Título", "Izenburua"), 
                            t("Autor", "Egilea"), 
                            t("Año", "Urtea"), 
                            t("Nº Bibliotecas en Red", "Sarean Liburutegi Kopurua")
                        ]
                        st.dataframe(df_rec_gen, use_container_width=True, hide_index=True)
                       
                        csv_gen = df_rec_gen.to_csv(index=False, sep=';', encoding="utf-8-sig")
                        st.download_button(
                            t("📥 Descargar Listado General (CSV)", "📥 Zerrenda Orokorra Deskargatu (CSV)"), 
                            csv_gen, 
                            "sugerencias_generales.csv", 
                            "text/csv"
                        )
                    else:
                        st.info(t("No se encontraron recomendaciones pendientes.", "Ez da gomendiorik aurkitu."))
            
            # ------------------------------------------
            # B) RECOMENDACIONES POR CDU
            # ------------------------------------------
            with subtab_rec_cdu:
                st.subheader(t("🎯 Sugerencias de Adquisición por CDU", "🎯 CDU arabera Erosketa Gomendioak"))
               
                if conn is None:
                    st.error(t("No hay conexión activa con la base de datos.", "Ez dago datu-basearekin konexio aktiborik."))
                else:
                    col_f1, col_f2 = st.columns(2)
                    with col_f1:
                        limite_cdu = st.number_input(
                            t("Máximo por subcategoría:", "Gehieneko subcategoriako:"), 
                            min_value=1, max_value=100, value=10, key="l_cdu"
                        )
                    with col_f2:
                        anio_minimo = st.number_input(
                            t("Año mínimo publicación:", "Argitalpen urte minimoa:"), 
                            min_value=1800, max_value=2026, value=2015, key="a_cdu"
                        )
    
                    busqueda_cdu = st.text_input(
                        t("⌨️ Filtrar por CDU específica (Soporta comodines como `*`):", "⌨️ CDU zehatzaren arabera iragazi (`*` onartzen du):"),
                        value="",
                        placeholder=t("Ej: 004* para informática", "Adib: 004* informatika"),
                        key="b_cdu_libre"
                    ).strip().upper()
    
                    biblioteca = biblioteca_seleccionada.upper().strip()
    
                    query_cdu = """
                    SELECT
                        l.id_sistema, l.titulo, l.autor, l.anio, l.cdu,
                        COUNT(DISTINCT e.biblioteca) AS id_red_bibliotecas,
                        GROUP_CONCAT(e.signatura, '||') AS todas_signaturas
                    FROM libros l
                    JOIN ejemplares e ON l.id_sistema = e.id_sistema
                    WHERE l.id_sistema NOT IN (
                        SELECT DISTINCT id_sistema FROM ejemplares WHERE UPPER(TRIM(biblioteca)) = ?
                    )
                    AND CAST(COALESCE(l.anio, 0) AS INTEGER) >= ?
                    GROUP BY l.id_sistema, l.titulo, l.autor, l.anio, l.cdu
                    HAVING id_red_bibliotecas > 0
                    """
                   
                    with st.spinner(t("Modelando el embudo de categorías de la Red...", "Sareko kategoriatan embudoa modelatzen...")):
                        df_raw_cdu = pd.read_sql_query(query_cdu, conn, params=[biblioteca, int(anio_minimo)])
    
                    if df_raw_cdu.empty:
                        st.warning(t("No hay recomendaciones con la configuración de años actual.", "Ez dago gomendiorik uneko urte konfigurazioarekin."))
                    else:
                        if busqueda_cdu:
                            if '*' in busqueda_cdu:
                                import re
                                patron_escapado = re.escape(busqueda_cdu)
                                regex_patron = patron_escapado.replace(r'\*', '.*')
                                df_raw_cdu = df_raw_cdu[
                                    df_raw_cdu['cdu'].astype(str).str.upper().str.strip().str.match(regex_patron, na=False)
                                ]
                            else:
                                df_raw_cdu = df_raw_cdu[
                                    df_raw_cdu['cdu'].astype(str).str.upper().str.strip().str.startswith(busqueda_cdu, na=False)
                                ]
    
                        if df_raw_cdu.empty:
                            st.info(t("ℹ️ Ninguna sugerencia de la Red coincide con el patrón de CDU introducido.", "ℹ️ Sareko gomendiorik ez dator bat sartutako CDU ereduarekin."))
                        else:
                            def clasificar_infantil(todas_sigs):
                                if not todas_sigs: return None
                                sigs = [s.strip().upper() for s in str(todas_sigs).split('||') if s.strip()]
                                for sig in sigs:
                                    match_edad = re.search(r'\b(I0|I1|I2|I3|JN)\b', sig)
                                    if match_edad: return match_edad.group(1)
                                    match_mat = re.search(r'\bI\s+([0-9])\b', sig)
                                    if match_mat: return f"I CDU {match_mat.group(1)}"
                                    match_typo = re.search(r'\bI([4-9])\b', sig)
                                    if match_typo: return f"I CDU {match_typo.group(1)}"
                                return None
    
                            def clasificar_libro(row):
                                cdu = str(row["cdu"]).strip().upper()
                                if cdu.startswith("087.5"):
                                    cat_inf = clasificar_infantil(row.get("todas_signaturas", ""))
                                    if cat_inf: return "Infantil", cat_inf
                                    return None, None
                                if cdu.startswith("821"):
                                    return "Adultos", "Ficción"
                                m = re.match(r'^(\d)', cdu)
                                if m:
                                    digito = m.group(1)
                                    if digito in ['0', '1', '2', '3', '5', '6', '7', '8', '9']:
                                        return "Adultos", f"CDU {digito}"
                                return None, None
    
                            res_eval = df_raw_cdu.apply(clasificar_libro, axis=1)
                            df_raw_cdu["subtab_destino"] = [r[0] for r in res_eval]
                            df_raw_cdu["categoria_final"] = [r[1] for r in res_eval]
                           
                            df_raw_cdu = df_raw_cdu[df_raw_cdu["subtab_destino"].notna()].copy()
                            df_raw_cdu = df_raw_cdu.sort_values("id_red_bibliotecas", ascending=False)
    
                            sub_adultos, sub_infantil = st.tabs([
                                t("👨‍💼 Sección Adultos", "👨‍💼 Helduen Atala"),
                                t("👶 Sección Infantil", "👶 Haur Atala")
                            ])
    
                            with sub_adultos:
                                menus_adultos = {
                                    "Ficción": t("📖 Ficción Adultos (821)", "📖 Helduen Fikzioa (821)"),
                                    "CDU 0": t("📂 CDU 0 - Generalidades", "📂 CDU 0 - Orokorra"),
                                    "CDU 1": t("📂 CDU 1 - Filosofía / Psicología", "📂 CDU 1 - Filosofia / Psikologia"),
                                    "CDU 2": t("📂 CDU 2 - Religión / Teología", "📂 CDU 2 - Erlijioa / Teologia"),
                                    "CDU 3": t("📂 CDU 3 - Ciencias Sociales / Economía", "📂 CDU 3 - Gizarte Zientziak / Ekonomia"),
                                    "CDU 5": t("📂 CDU 5 - Ciencias Puras / Naturales", "📂 CDU 5 - Zientzia Pureak / Natur Zientziak"),
                                    "CDU 6": t("📂 CDU 6 - Ciencias Aplicadas / Technology", "📂 CDU 6 - Zientzia Aplikatuak"),
                                    "CDU 7": t("📂 CDU 7 - Bellas Artes / Deportes", "📂 CDU 7 - Arte Ederrak / Kirolak"),
                                    "CDU 8": t("📂 CDU 8 - Lingüística / Literatura (Excl. Narrativa)", "📂 CDU 8 - Linguistika / Literatura"),
                                    "CDU 9": t("📂 CDU 9 - Geografía / Historia", "📂 CDU 9 - Geografia / Historia")
                                }
                                hay_ad = False
                                for k, titulo_ex in menus_adultos.items():
                                    g = df_raw_cdu[(df_raw_cdu["subtab_destino"] == "Adultos") & (df_raw_cdu["categoria_final"] == k)].head(limite_cdu)
                                    if not g.empty:
                                        hay_ad = True
                                        with st.expander(f"{titulo_ex} ({len(g)} ítems)"):
                                            st.dataframe(g[["titulo", "autor", "anio", "cdu", "id_red_bibliotecas"]], use_container_width=True, hide_index=True)
                                if not hay_ad: 
                                    st.info(t("No hay sugerencias para adultos con este filtro.", "Ez dago gomendiorik helduentzat filtro honekin."))
    
                            with sub_infantil:
                                menus_infantil = {
                                    "I0": t("👶 I0 - Bebeteca", "👶 I0 - Bebeteka"),
                                    "I1": t("🧸 I1 - Hasta 6 años", "🧸 I1 - 6 urte arte"),
                                    "I2": t("🎒 I2 - 7 a 9 años", "🎒 I2 - 7 eta 9 urte"),
                                    "I3": t("🛡️ I3 - 10 a 12 años", "🛡️ I3 - 10 eta 12 urte"),
                                    "JN": t("⚡ JN - Juvenil", "⚡ JN - Jubenil"),
                                    "I CDU 0": t("📚 I CDU 0 - Generalidades", "📚 I CDU 0 - Orokorra"),
                                    # ... (resto de entradas similares)
                                    "I CDU 9": t("📚 I CDU 9 - Geografía e Historia", "📚 I CDU 9 - Geografia eta Historia")
                                }
                                hay_inf = False
                                for k, titulo_ex in menus_infantil.items():
                                    g = df_raw_cdu[(df_raw_cdu["subtab_destino"] == "Infantil") & (df_raw_cdu["categoria_final"] == k)].head(limite_cdu)
                                    if not g.empty:
                                        hay_inf = True
                                        with st.expander(f"{titulo_ex} ({len(g)} ítems)"):
                                            st.dataframe(g[["titulo", "autor", "anio", "cdu", "id_red_bibliotecas"]], use_container_width=True, hide_index=True)
                                if not hay_inf: 
                                    st.info(t("No hay sugerencias infantiles con este filtro.", "Ez dago gomendiorik haurrentzat filtro honekin."))
    
    
    

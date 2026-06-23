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

# ==========================================
# CONFIGURACIÓN DE BASE DE DATOS
# ==========================================
DB_PATH = "gestion_coleccion.db"
# 1. CAMBIO CLAVE: Cambiamos dl=0 por dl=1 al final de la URL para forzar la descarga directa del binario (.db)
DB_URL = "https://www.dropbox.com/scl/fi/zlhw2qkfpebtvzaimxto1/bibliotecas_navarra2.db?rlkey=fg46liauy6omsq3dkz4gnn5pk&st=jr3xe9k4&dl=1"

def asegurar_base_de_datos():
    """Maneja la descarga del archivo en disco. 
    Limpia archivos HTML corruptos previos y descarga el archivo SQLite real."""
    debe_descargar = False
    
    if not os.path.exists(DB_PATH):
        debe_descargar = True
    elif os.path.getsize(DB_PATH) < 10000:  
        # 2. DETECCIÓN: Si el archivo mide menos de 10KB, es el texto HTML de la vista previa vieja.
        # Lo eliminamos para que no interfiera con SQLite.
        os.remove(DB_PATH)  
        debe_descargar = True

    if debe_descargar:
        with st.spinner("Descargando base de datos de la colección (500MB)... Esto puede tardar un minuto la primera vez."):
            try:
                # Al ir con dl=1, urlretrieve descargará los ~500MB reales directamente al disco
                urllib.request.urlretrieve(DB_URL, DB_PATH)
                st.toast("¡Base de datos descargada con éxito!", icon="📥")
                return True
            except Exception as e:
                st.error(f"Error crítico al descargar la base de datos desde Dropbox: {e}")
                return False
    return True

# ==========================================
# EJECUCIÓN DE LA VERIFICACIÓN
# ==========================================
# Llamamos a la función antes de crear cualquier conexión 'conn = sqlite3.connect(...)'
if asegurar_base_de_datos():
    conn = sqlite3.connect(DB_PATH)
else:
    conn = None
    st.error("No se pudo establecer la conexión porque falló la preparación del archivo .db")

@st.cache_resource
def obtener_conexion_db():
    """Únicamente se encarga de cachear el recurso de conexión, 
    completamente limpio de lógica visual compleja."""
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        return conn
    except Exception as e:
        return None

# Inicializar la lógica de manera secuencial y segura
if asegurar_base_de_datos():
    conn = obtener_conexion_db()
    if conn is None:
        st.error("Error al conectar con el archivo SQLite.")
else:
    conn = None


# ==========================================
# FUNCIONES AUXILIARES DE RECOMENDACIÓN
# ==========================================
def obtener_recomendaciones_automaticas(conexion, bibliotecas, limite=50):
    if isinstance(bibliotecas, str):
        bibliotecas = [bibliotecas]
    elif not isinstance(bibliotecas, (list, tuple)):
        st.error(f"❌ 'bibliotecas' debe ser texto o lista. Recibí: {type(bibliotecas)}")
        return pd.DataFrame()
   
    if not bibliotecas:
        st.error("❌ Debes indicar al menos una biblioteca.")
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
        st.error(f"❌ Error en la consulta SQL: {str(e)}")
        return pd.DataFrame()

import pandas as pd

def obtener_recomendaciones_por_materia(conexion, biblioteca, materias_seleccionadas, anios, min_ejemplares, limite):
    anio_corte = 2026 - anios
    
    # Generamos tantos signos de interrogación como elementos tenga nuestra lista mapeada
    placeholders = ",".join(["?"] * len(materias_seleccionadas))
    
    query = f"""
        SELECT c.id_sistema, c.titulo, c.autor, c.editorial, c.anio, c.cdu, c.isbn, c.materias, c.ejemplares, c.bibliotecas
        FROM catalogo c
        WHERE c.anio >= ?
          AND c.ejemplares >= ?
          AND c.id_sistema IN (
              SELECT id_sistema 
              FROM materias 
              WHERE materia IN ({placeholders})
          )
          AND c.id_sistema NOT IN (
              SELECT id_sistema FROM inventario_centros WHERE codigo_biblioteca = ?
          )
        ORDER BY c.ejemplares DESC
        LIMIT ?
    """
    
    # Combinamos todos los parámetros en el orden correcto para la tupla de ejecución de SQLite
    parametros = [anio_corte, min_ejemplares] + materias_seleccionadas + [biblioteca, limite]
    
    try:
        return pd.read_sql_query(query, conexion, params=parametros)
    except Exception as e:
        print(f"Error en consulta: {e}")
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
        title = title_match.group(1).strip() if title_match else "Título no detectado"
       
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

st.markdown('<div class="main-title">📚 Gestión de la colección</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Herramienta para ayudarte a conocer un poco mejor la colección de tu biblioteca</div>', unsafe_allow_html=True)

# ==========================================
# PANEL LATERAL (SIDEBAR)
# ==========================================
with st.sidebar:
    st.header("🏢 1. Selección de Biblioteca")
    biblioteca_seleccionada = st.selectbox("Biblioteca:", options=list(BIBLIOTECAS.keys()))
    poblacion_atendida = BIBLIOTECAS[biblioteca_seleccionada]

    st.markdown("---")

    if not st.session_state['analizado']:
        st.header("📂 2. Carga de Archivos")
        uploaded_topo = st.file_uploader("Archivo Topográfico (.txt) *Requerido*", type=["txt"])
        uploaded_catalogo = st.file_uploader("Catálogo Completo (.txt) *Requerido*", type=["txt"])
        uploaded_nunca = st.file_uploader("No Prestados (.txt)", type=["txt"])
        uploaded_mas2 = st.file_uploader("Más Prestados (.txt)", type=["txt"])

        st.markdown("---")
        
        # Seteamos las variables fijas por defecto para evitar el NameError
        tipo_analisis = "Clasificación Mixta Estándar (CDU + Letras)"
        num_caracteres = 3
       
        if st.button("🚀 Analizar Fondos", type="primary", use_container_width=True):
            if not uploaded_topo or not uploaded_catalogo:
                st.error("⚠️ Sube los archivos requeridos.")
            else:
                with st.spinner("Procesando datos..."):
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
        st.success("✅ Datos cargados en memoria.")
        if st.button("🔄 Cambiar / Volver a subir archivos", use_container_width=True):
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
    m1.metric("📖 Total Volúmenes", f"{total_docs:,}")
    m2.metric("🪪 Índice de Circulación", f"{pct_prestados:.1f}%")
    m3.metric("📅 Edad Media del Fondo", f"{int(edad_media)}" if not np.isnan(edad_media) else "N/A")
    m4.metric("👥 Docs por Habitante", f"{docs_por_habitante:.2f}")
   
    if huerfanos > 0:
        st.caption(f"ℹ️ Se han omitido {huerfanos} registros del topográfico por incoherencias con el catálogo.")

    st.markdown("---")

    # LAS DOS GRANDES CATEGORÍAS SOLICITADAS
    pestana_analisis, pestana_compras = st.tabs([
        "📊 1. Análisis de la Colección", 
        "🎯 2. Recomendaciones de Compra"
    ])

    # ==========================================
    # BLOQUE 1: ANÁLISIS DE LA COLECCIÓN
    # ==========================================
    with pestana_analisis:
        subtab_general, subtab_cdu, subtab_signatura = st.tabs([
            "📈 A) Análisis General", 
            "🗂️ B) Análisis por CDU", 
            "🔎 C) Análisis Profundo por Signatura"
        ])
        
        # A) ANÁLISIS GENERAL
        with subtab_general:
            st.subheader("⚖️ Diagnóstico según Pautas Oficiales (IFLA)")
           
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
                    st.error(f"🚨 **Alerta:** Suelo mínimo absoluto IFLA es de 2.500 obras. Tienes **{total_docs:,}**.")
                elif total_docs < pauta_min:
                    st.warning(f"⚠️ **Déficit de fondo:** Recomendado para tu población: {pauta_min:,}-{pauta_max:,}. Tienes **{total_docs:,}** u.")
                elif total_docs > pauta_max:
                    st.info(f"ℹ️ **Fondo extenso:** El rango inicial recomendado es {pauta_min:,}-{pauta_max:,}. Tienes **{total_docs:,}** u.")
                else:
                    st.success(f"✅ **Óptimo:** Volumen bruto adecuado dentro del rango ({pauta_min:,}-{pauta_max:,}).")

            with col_al2:
                # Diagnóstico corregido por ratio de habitante (Evita falsos óptimos en poblaciones pequeñas)
                if docs_por_habitante > 3.5:
                    st.warning(f"⚠️ **Colección demasiado grande:** Tienes **{docs_por_habitante:.2f}** libros por persona (Límite óptimo: {pauta_hab} - Máx sugerido: 3.5).")
                elif docs_por_habitante < pauta_hab:
                    st.warning(f"⚠️ **Ratio Bajo:** **{docs_por_habitante:.2f}** doc/hab. (Mínimo recomendado: {pauta_hab}).")
                else:
                    st.success(f"✅ **Ratio Óptimo:** **{docs_por_habitante:.2f}** doc/hab.")

            st.write("#### 📊 Distribución Macroscópica")
            
            def clasificar_macro(cat):
                # Limpiamos espacios y pasamos a mayúsculas para asegurar homogeneidad
                c = str(cat).strip().upper()
                
                # 1. Filtro de Audiovisuales (Tiene prioridad: atrapa 'DVD', 'I DVD', 'CD', etc.)
                if "DVD" in c or "AUDIOVISUAL" in c or "CD" in c: 
                    return "Audiovisuales"
                
                # 2. Filtro de Infantil / Juvenil mediante Expresión Regular
                # ^(I|JN|IC|IP|IT|INFANTIL|JUVENIL) -> Debe EMPEZAR por alguno de estos códigos
                # (\s|\d+|-|$) -> Seguido de un espacio, un número, un guion o el final de la línea
                if re.match(r'^(I|JN|IC|IP|IT|INFANTIL|JUVENIL)(\s|\d+|-|$)', c): 
                    return "Infantil/Juvenil"
                
                # 3. Si no cumple lo anterior, se clasifica como Adultos
                return "Adultos"

            # Aplicamos la nueva clasificación corregida
            df_completo['macro_seccion'] = df_completo['categoria'].apply(clasificar_macro)
            macro_counts = df_completo['macro_seccion'].value_counts()
           
            p_adultos = (macro_counts.get("Adultos", 0) / total_docs * 100) if total_docs > 0 else 0
            p_infantil = (macro_counts.get("Infantil/Juvenil", 0) / total_docs * 100) if total_docs > 0 else 0
            p_audio = (macro_counts.get("Audiovisuales", 0) / total_docs * 100) if total_docs > 0 else 0

            tabla_macro = pd.DataFrame({
                "Sección": ["Adultos", "Infantil/Juvenil", "Audiovisuales"],
                "Distribución": [f"{p_adultos:.1f}%", f"{p_infantil:.1f}%", f"{p_audio:.1f}%"]
        
            })
            st.dataframe(tabla_macro, use_container_width=True, hide_index=True)

            st.write("#### 📈 Nivel de Rotación Física")
            status_map = {0: 'Nunca prestado', 1: 'Prestado', 2: 'Muy prestado'}
            status_counts = df_completo['prestamos'].map(status_map).value_counts().reset_index()
            status_counts.columns = ['Estado', 'Cantidad']
            fig_pie = px.pie(status_counts, values='Cantidad', names='Estado', hole=0.4, color_discrete_sequence=px.colors.qualitative.Safe)
            st.plotly_chart(fig_pie, use_container_width=True)

            st.write("#### ⏳ Cronología de Ediciones")
            if not df_completo['year'].dropna().empty:
                fig_hist = px.histogram(df_completo, x='year', nbins=25, labels={'year': 'Año de Publicación'}, color_discrete_sequence=['#1E3A8A'])
                st.plotly_chart(fig_hist, use_container_width=True)


        # B) ANÁLISIS POR CDU
        with subtab_cdu:
            st.subheader("🗂️ Concentración y Rendimiento por Secciones")
           
            # 1. Generar métricas base globales
            df_metrics = df_completo.groupby('categoria').agg(
                Volúmenes=('record_id', 'count'),
                Prestados=('prestado', 'sum'),
                Año_Medio=('year', 'mean')
            ).reset_index()
           
            df_metrics['% Uso (Rotación)'] = (df_metrics['Prestados'] / df_metrics['Volúmenes'] * 100).round(1)
            df_metrics['Año Medio Edición'] = df_metrics['Año_Medio'].fillna(0).astype(int)
           
            # 2. Segmentar de forma limpia y estricta entre Infantil/Juvenil y Adultos
            def es_categoria_infantil(categoria):
                cat_str = str(categoria).upper()
                # 1. Si contiene la palabra explícita (viene de nuestro analizador estándar)
                if "INFANTIL" in cat_str or "JUVENIL" in cat_str:
                    return True
                # 2. Si se está usando el análisis por longitud fija y empieza por siglas infantiles exactas
                # I, I1, I2, I3, JN, IC, IP, IT (evita que "Ficción" coincida con "IC")
                if re.match(r'^(I[0-9]?|JN|IC|IP|IT)(\s|$)', cat_str):
                    return True
                return False

            df_metrics['es_infantil'] = df_metrics['categoria'].apply(es_categoria_infantil)
            
            df_adultos = df_metrics[~df_metrics['es_infantil']].sort_values(by='Volúmenes', ascending=False)
            df_infantil = df_metrics[df_metrics['es_infantil']].sort_values(by='Volúmenes', ascending=False)
           
            # ==========================================
            # 📊 GRÁFICO Y TABLA - SECCIÓN ADULTOS
            # ==========================================
            st.markdown("### 👨‍💼 Análisis Sección Adultos")
            if not df_adultos.empty:
                fig_bar_adultos = px.bar(
                    df_adultos, 
                    x='categoria', 
                    y='Volúmenes', 
                    color='% Uso (Rotación)', 
                    title="Adultos: Volumen vs Rotación por Categoría",
                    color_continuous_scale="Blues",
                    labels={'categoria': 'Categoría / CDU', 'Volúmenes': 'Nº Volúmenes'}
                )
                st.plotly_chart(fig_bar_adultos, use_container_width=True)
               
                st.dataframe(
                    df_adultos[['categoria', 'Volúmenes', '% Uso (Rotación)', 'Año Medio Edición']], 
                    use_container_width=True, 
                    hide_index=True
                )
            else:
                st.info("ℹ️ No hay datos suficientes para generar el análisis de Adultos.")
           
            st.markdown("---")
            
            # ==========================================
            # 📊 GRÁFICO Y TABLA - SECCIÓN INFANTIL
            # ==========================================
            st.markdown("### 👶 Análisis Sección Infantil / Juvenil")
            if not df_infantil.empty:
                fig_bar_infantil = px.bar(
                    df_infantil, 
                    x='categoria', 
                    y='Volúmenes', 
                    color='% Uso (Rotación)', 
                    title="Infantil/Juvenil: Volumen vs Rotación por Categoría",
                    color_continuous_scale="Purples",
                    labels={'categoria': 'Categoría / Tejuelo', 'Volúmenes': 'Nº Volúmenes'}
                )
                st.plotly_chart(fig_bar_infantil, use_container_width=True)
               
                st.dataframe(
                    df_infantil[['categoria', 'Volúmenes', '% Uso (Rotación)', 'Año Medio Edición']], 
                    use_container_width=True, 
                    hide_index=True
                )
            else:
                st.info("ℹ️ No hay datos suficientes para generar el análisis Infantil.")

         # C) ANÁLISIS PROFUNDO POR SIGNATURA
        with subtab_signatura:
            st.subheader("🔎 Analiza la colección a través de las signaturas.")
            
           
            # Función de seguridad para la clasificación de secciones
            def identificar_infantil(categoria):
                cat_str = str(categoria).upper()
                if "INFANTIL" in cat_str or "JUVENIL" in cat_str: return True
                if re.match(r'^(I[0-9]?|JN|IC|IP|IT)(\s|$)', cat_str): return True
                return False
       
            # Aseguramos la columna de control en el dataframe de trabajo
            df_completo['es_infantil'] = df_completo['categoria'].apply(identificar_infantil)
       
            # --- 1. FILTRO DE PÚBLICO / SECCIÓN ---
            filtro_pub = st.radio("1. Selecciona la Sección:", ["📚 Todo el fondo", "👨‍💼 Solo Adultos", "👶 Solo Infantil / Juvenil"], horizontal=True)
           
            df_nivel1 = df_completo.copy()
            if "Adultos" in filtro_pub:
                df_nivel1 = df_nivel1[~df_nivel1['es_infantil']]
            elif "Infantil" in filtro_pub:
                df_nivel1 = df_nivel1[df_nivel1['es_infantil']]
       
            st.markdown("---")
       
            # --- 2. PANEL DE CONTROL Y CRITERIOS DE BÚSQUEDA (DESPLEGADOS) ---
            st.markdown("#### 🎯 Criterios de Selección y Búsqueda")
           
            # Primera fila de filtros: Búsqueda libre e Historial de Préstamos
            col_busqueda, col_prestamos = st.columns([2, 1])
           
            with col_busqueda:
                busqueda_sig = st.text_input(
                    "⌨️ Buscar por Signatura / CDU (Soporta comodines como `*`):",
                    value="",
                    placeholder="Ej: *(460.16)* para Navarra, 821* para literatura, o ENG * para libros en inglés."
                ).strip().upper()
               
            with col_prestamos:
                filtro_pr = st.selectbox(
                    "🪪 Historial Préstamos:",
                    ["Todos", "Nunca prestado (0)", "Préstamo Estándar (1)", "Alta Demanda (2)"]
                )
       
            # Segunda fila de filtros: Jerarquía de categorías (Visibles y dinámicos)
            col_cat1, col_cat2 = st.columns(2)
           
            with col_cat1:
                opciones_cat = ["Todas"] + sorted(df_nivel1['categoria'].dropna().unique().tolist())
                filtro_cat = st.selectbox("🗂️ Categoría Principal:", opciones_cat)
       
            # Filtrado intermedio para que el segundo desplegable responda al primero
            df_nivel2 = df_nivel1.copy()
            if filtro_cat != "Todas":
                df_nivel2 = df_nivel2[df_nivel2['categoria'] == filtro_cat]
       
            with col_cat2:
                def extraer_raiz(sig):
                    s = str(sig).strip().upper()
                    m = re.match(r'^([A-Z]*\s*\d{2})', s)
                    if m: return m.group(1)
                    return s.split()[0][:3]
       
                raices_existentes = df_nivel2['signatura_real'].dropna().apply(extraer_raiz).unique()
                opciones_sub = ["Todas"] + sorted(raices_existentes.tolist())
                filtro_sub = st.selectbox("🔎 Sub-signatura de la categoría:", opciones_sub)
       
            st.markdown("---")
       
            # --- 3. APLICACIÓN DE LA LÓGICA DE FILTRADO COMBINADA ---
            df_final_expurgo = df_nivel1.copy()
           
            # 1. Filtrado por la caja de texto (Soporte de comodines '*')
            if busqueda_sig:
                if '*' in busqueda_sig:
                    import re
                    # 1. Escapamos caracteres especiales de regex
                    patron_escapado = re.escape(busqueda_sig)
                    # 2. Convertimos el asterisco en comodín compatible con PyArrow
                    regex_patron = patron_escapado.replace(r'\*', '.*')
                   
                    df_final_expurgo = df_final_expurgo[
                        df_final_expurgo['signatura_real'].str.upper().str.strip().str.match(regex_patron, na=False)
                    ]
                else:
                    # Si no lleva asteriscos, mantiene el comportamiento limpio de "empieza por"
                    df_final_expurgo = df_final_expurgo[
                        df_final_expurgo['signatura_real'].str.upper().str.strip().str.startswith(busqueda_sig, na=False)
                    ]

            # 2. Filtrado por Desplegables de Categorías (Ahora acumulativos)
            if filtro_cat != "Todas":
                df_final_expurgo = df_final_expurgo[df_final_expurgo['categoria'] == filtro_cat]
            if filtro_sub != "Todas":
                df_final_expurgo = df_final_expurgo[
                    df_final_expurgo['signatura_real'].str.upper().str.startswith(filtro_sub, na=False)
                ]
           
            # 3. Filtrado por Historial de Préstamos
            if "Nunca" in filtro_pr:
                df_final_expurgo = df_final_expurgo[df_final_expurgo['prestamos'] == 0]
            elif "Estándar" in filtro_pr:
                df_final_expurgo = df_final_expurgo[df_final_expurgo['prestamos'] == 1]
            elif "Alta" in filtro_pr:
                df_final_expurgo = df_final_expurgo[df_final_expurgo['prestamos'] == 2]
       
            # --- 5. RENDERIZADO DE LA TABLA DETALLADA ---
            st.markdown(f"**Resultados encontrados: {len(df_final_expurgo)} documentos**")
           
            tabla_mostrar = df_final_expurgo[['record_id', 'signatura_real', 'titulo', 'year', 'categoria', 'prestamos']].copy()
            tabla_mostrar.columns = ['id_sistema', 'Signatura', 'Título', 'Año', 'Categoría', 'Préstamos']
           
            st.dataframe(tabla_mostrar, use_container_width=True, hide_index=True)

            # --- 6. NUEVA TABLA DINÁMICA DE RESUMEN EJECUTIVO ---
            st.markdown("### 📊 Indicadores Globales de la Selección")
           
            if not df_final_expurgo.empty:
                # A) Número de volúmenes totales en el filtro activo
                num_volumenes = len(df_final_expurgo)
               
                # B) % de la colección que acumula préstamos
                libros_prestados = (df_final_expurgo['prestamos'] > 0).sum()
                pct_prestados = round((libros_prestados / num_volumenes) * 100, 1)
               
                # C) Año medio de edición del tramo seleccionado
                anios_validos = df_final_expurgo['year'].dropna()
                if not anios_validos.empty:
                    anio_medio_col = int(anios_validos.mean())
                else:
                    anio_medio_col = "Sin datos de año"
               
                # Estructuramos los datos calculados en un pequeño DataFrame resumen
                df_resumen_kpi = pd.DataFrame([{
                    "Número de volúmenes": f"{num_volumenes} ej.",
                    "% de préstamos (Uso Activo)": f"{pct_prestados} %",
                    "Año medio de la colección": anio_medio_col
                }])
               
                # Renderizado estilizado de la tabla de indicadores
                st.dataframe(df_resumen_kpi, use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ Modifica los criterios de búsqueda para calcular los indicadores del fondo.")


    # ==========================================
    # BLOQUE 2: RECOMENDACIONES DE COMPRA
    # ==========================================
    with pestana_compras:
        subtab_rec_gen, subtab_rec_cdu, subtab_rec_materias = st.tabs([
            "🌐 A) Recomendaciones Generales", 
            "📚 B) Recomendaciones por CDU",
            "🎯 C) Recomendaciones por Materias" 
        ])
        
        # A) RECOMENDACIONES GENERALES
        with subtab_rec_gen:
            st.subheader("📈 Títulos más Populares en la Red Ausentes en tu Centro")
            limite_gen = st.number_input("Número de títulos a sugerir:", min_value=5, max_value=200, value=50, step=5)
            
            if conn is not None:
                df_rec_gen = obtener_recomendaciones_automaticas(conn, biblioteca_seleccionada, limite_gen)
                if not df_rec_gen.empty:
                    df_rec_gen.columns = ["ID Sistema", "Título", "Autor", "Año", "Nº Bibliotecas en Red"]
                    st.dataframe(df_rec_gen, use_container_width=True, hide_index=True)
                    
                    csv_gen = df_rec_gen.to_csv(index=False, sep=';', encoding="utf-8-sig")
                    st.download_button("📥 Descargar Listado General (CSV)", csv_gen, "sugerencias_generales.csv", "text/csv")
                else:
                    st.info("No se encontraron recomendaciones pendientes.")

      # ------------------------------------------
        # B) RECOMENDACIONES POR CDU (CON REGLAS ESTRICTAS DE FILTRADO ANTI-RUIDO)
        # ------------------------------------------
        with subtab_rec_cdu:
            st.subheader("🎯 Sugerencias de Adquisición por CDU")
            
            if conn is None:
                st.error("No hay conexión activa con la base de datos.")
            else:
                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    limite_cdu = st.number_input("Máximo por subcategoría:", min_value=1, max_value=100, value=10, key="l_cdu")
                with col_f2:
                    anio_minimo = st.number_input("Año mínimo publicación:", min_value=1800, max_value=2026, value=2015, key="a_cdu")

                # Caja de búsqueda libre por CDU
                busqueda_cdu = st.text_input(
                    "⌨️ Filtrar por CDU específica (Soporta comodines como `*`):",
                    value="",
                    placeholder="Ej: 004* para informática",
                    key="b_cdu_libre"
                ).strip().upper()

                biblioteca = biblioteca_seleccionada.upper().strip()

                # Query optimizada para el procesamiento
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
                
                with st.spinner("Modelando el embudo de categorías de la Red..."):
                    df_raw_cdu = pd.read_sql_query(query_cdu, conn, params=[biblioteca, int(anio_minimo)])

                if df_raw_cdu.empty:
                    st.warning("No hay recomendaciones con la configuración de años actual.")
                else:
                    # --- APLICACIÓN DEL FILTRO DE BÚSQUEDA LIBRE DE CDU ---
                    if busqueda_cdu:
                        if '*' in busqueda_cdu:
                            import re
                            # Escapamos la cadena para proteger paréntesis/puntos y cambiamos '*' por '.*'
                            patron_escapado = re.escape(busqueda_cdu)
                            regex_patron = patron_escapado.replace(r'\*', '.*')
                            df_raw_cdu = df_raw_cdu[
                                df_raw_cdu['cdu'].astype(str).str.upper().str.strip().str.match(regex_patron, na=False)
                            ]
                        else:
                            # Comportamiento por defecto: "empieza por"
                            df_raw_cdu = df_raw_cdu[
                                df_raw_cdu['cdu'].astype(str).str.upper().str.strip().str.startswith(busqueda_cdu, na=False)
                            ]

                    # Validamos si tras el filtro de búsqueda sigue habiendo datos
                    if df_raw_cdu.empty:
                        st.info("ℹ️ Ninguna sugerencia de la Red coincide con el patrón de CDU introducido.")
                    else:
                        # Lógica interna de clasificación infantil limpia
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

                        # Embudo estricto de control de ruido solicitado
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
                        
                        # Eliminamos el ruido no clasificado
                        df_raw_cdu = df_raw_cdu[df_raw_cdu["subtab_destino"].notna()].copy()
                        df_raw_cdu = df_raw_cdu.sort_values("id_red_bibliotecas", ascending=False)

                        # Subpestañas finales internas
                        sub_adultos, sub_infantil = st.tabs(["👨‍💼 Sección Adultos", "👶 Sección Infantil"])

                        with sub_adultos:
                            menus_adultos = {
                                "Ficción": "📖 Ficción Adultos (821)",
                                "CDU 0": "📂 CDU 0 - Generalidades",
                                "CDU 1": "📂 CDU 1 - Filosofía / Psicología",
                                "CDU 2": "📂 CDU 2 - Religión / Teología",
                                "CDU 3": "📂 CDU 3 - Ciencias Sociales / Economía",
                                "CDU 5": "📂 CDU 5 - Ciencias Puras / Naturales",
                                "CDU 6": "📂 CDU 6 - Ciencias Aplicadas / Technology",
                                "CDU 7": "📂 CDU 7 - Bellas Artes / Deportes",
                                "CDU 8": "📂 CDU 8 - Lingüística / Literatura (Excl. Narrativa)",
                                "CDU 9": "📂 CDU 9 - Geografía / Historia"
                            }
                            hay_ad = False
                            for k, titulo_ex in menus_adultos.items():
                                g = df_raw_cdu[(df_raw_cdu["subtab_destino"] == "Adultos") & (df_raw_cdu["categoria_final"] == k)].head(limite_cdu)
                                if not g.empty:
                                    hay_ad = True
                                    with st.expander(f"{titulo_ex} ({len(g)} ítems)"):
                                        st.dataframe(g[["titulo", "autor", "anio", "cdu", "id_red_bibliotecas"]], use_container_width=True, hide_index=True)

                            if not hay_ad: st.info("No hay sugerencias para adultos con este filtro.")

                        with sub_infantil:
                            menus_infantil = {
                                "I0": "👶 I0 - Bebeteca", "I1": "🧸 I1 - Hasta 6 años",
                                "I2": "🎒 I2 - 7 a 9 años", "I3": "🛡️ I3 - 10 a 12 años", "JN": "⚡ JN - Juvenil",
                                "I CDU 0": "📚 I CDU 0 - Generalidades", "I CDU 1": "📚 I CDU 1 - Filosofía",
                                "I CDU 2": "📚 I CDU 2 - Religión", "I CDU 3": "📚 I CDU 3 - Ciencias Sociales",
                                "I CDU 4": "📚 I CDU 4 - Lengua", "I CDU 5": "📚 I CDU 5 - Ciencias Puras",
                                "I CDU 6": "📚 I CDU 6 - Ciencias Aplicadas", "I CDU 7": "📚 I CDU 7 - Arte / Deportes",
                                "I CDU 8": "📚 I CDU 8 - Literatura", "I CDU 9": "📚 I CDU 9 - Geografía e Historia"
                            }
                            hay_inf = False
                            for k, titulo_ex in menus_infantil.items():
                                g = df_raw_cdu[(df_raw_cdu["subtab_destino"] == "Infantil") & (df_raw_cdu["categoria_final"] == k)].head(limite_cdu)
                                if not g.empty:
                                    hay_inf = True
                                    with st.expander(f"{titulo_ex} ({len(g)} ítems)"):
                                        st.dataframe(g[["titulo", "autor", "anio", "cdu", "id_red_bibliotecas"]], use_container_width=True, hide_index=True)
                            
                            if not hay_inf: st.info("No hay sugerencias infantiles con este filtro.")

            # ======================================================================
            # C) RECOMENDACIONES POR MATERIAS (BÚSQUEDA POR DESCRIPTOR TEMÁTICO)
            # ======================================================================
            with subtab_rec_materias:
                st.subheader("📝 Análisis de Títulos por Materias Únicas")
                st.markdown("Consulta qué libros de una temática concreta triunfan en la Red de Navarra pero faltan en tu centro.")
                
                if conn is None:
                    st.error("No hay conexión activa con la base de datos.")
                else:
                    # 1. CARGAR Y NORMALIZAR EL LISTADO DE MATERIAS
                    try:
                        # Traemos el listado tal cual está en la base de datos
                        query_lista_materias = "SELECT DISTINCT materia FROM materias WHERE materia IS NOT NULL AND materia != ''"
                        df_lista_m = pd.read_sql_query(query_lista_materias, conn)
                        
                        # Homogeneizamos cualquier variante de guiones (- --,  -- , --) en un único " -- " estándar
                        df_lista_m['materia_limpia'] = df_lista_m['materia'].str.replace(r'\s*-?\s*--\s*', ' -- ', regex=True).str.strip()
                        
                        # Dividimos la cadena limpia en tres columnas jerárquicas
                        df_niveles = df_lista_m['materia_limpia'].str.split(' -- ', expand=True)
                        
                        # Aseguramos la existencia de al menos 3 columnas para evitar IndexError
                        for i in range(3):
                            if i not in df_niveles.columns:
                                df_niveles[i] = None
                                
                        df_lista_m['Nivel_1'] = df_niveles[0].str.strip()
                        df_lista_m['Nivel_2'] = df_niveles[1].str.strip()
                        df_lista_m['Nivel_3'] = df_niveles[2].str.strip()
                        
                        error_carga = False
                    except Exception as e:
                        st.error(f"Error al procesar la estructura de materias: {e}")
                        error_carga = True

                    if not error_carga:
                        # 2. INTERFAZ DE USUARIO: 3 CAJAS EN CASCADA
                        st.markdown("##### 🏷️ Selector Jerárquico del Descriptor Temático")
                        col_c1, col_c2, col_c3 = st.columns(3)
                        
                        with col_c1:
                            # Primer nivel: Materia principal (Ej: "Conflicto árabe-israelí", "Abogados")
                            opciones_n1 = sorted([str(x) for x in df_lista_m['Nivel_1'].dropna().unique() if x])
                            sel_n1 = st.selectbox("1️⃣ Materia Principal:", options=opciones_n1, key="mat_n1_in")
                        
                        with col_c2:
                            # Filtrar las opciones del segundo nivel basándonos en la elección del primero
                            df_filtro_n1 = df_lista_m[df_lista_m['Nivel_1'] == sel_n1]
                            opciones_n2 = sorted([str(x) for x in df_filtro_n1['Nivel_2'].dropna().unique() if x])
                            
                            if opciones_n2:
                                sel_n2 = st.selectbox("2️⃣ Subdivisión (Opcional):", options=["(Todas)"] + opciones_n2, key="mat_n2_in")
                            else:
                                sel_n2 = "(Todas)"
                                st.selectbox("2️⃣ Subdivisión:", options=["(Sin subdivisiones)"], disabled=True, key="mat_n2_dis")
                        
                        with col_c3:
                            # Filtrar el tercer nivel si se ha concretado el segundo
                            if sel_n2 != "(Todas)":
                                df_filtro_n2 = df_filtro_n1[df_filtro_n1['Nivel_2'] == sel_n2]
                                opciones_n3 = sorted([str(x) for x in df_filtro_n2['Nivel_3'].dropna().unique() if x])
                            else:
                                opciones_n3 = []
                                
                            if opciones_n3:
                                sel_n3 = st.selectbox("3️⃣ Subdivisión 2 (Opcional):", options=["(Todas)"] + opciones_n3, key="mat_n3_in")
                            else:
                                sel_n3 = "(Todas)"
                                st.selectbox("3️⃣ Subdivisión 2:", options=["(Sin subdivisiones)"], disabled=True, key="mat_n3_dis")

                        # 3. INTERSECCIÓN: Encontrar los términos originales "sucios" de la DB
                        df_seleccionado = df_lista_m[df_lista_m['Nivel_1'] == sel_n1]
                        if sel_n2 != "(Todas)":
                            df_seleccionado = df_seleccionado[df_seleccionado['Nivel_2'] == sel_n2]
                            if sel_n3 != "(Todas)":
                                df_seleccionado = df_seleccionado[df_seleccionado['Nivel_3'] == sel_n3]
                        
                        # Generamos la lista de strings reales (sucios) correspondientes a la selección limpia
                        lista_materias_raw = df_seleccionado['materia'].unique().tolist()

                        # Mostrar un pequeño texto informativo con lo que se va a buscar internamente
                        texto_visual_seleccion = sel_n1
                        if sel_n2 != "(Todas)": texto_visual_seleccion += f" ➔ {sel_n2}"
                        if sel_n3 != "(Todas)": texto_visual_seleccion += f" ➔ {sel_n3}"
                        st.caption(f"**Búsqueda activa:** `{texto_visual_seleccion}` *(mapeado a {len(lista_materias_raw)} variantes en la base de datos)*")

                        # 4. CONFIGURACIÓN DE PARÁMETROS NUMÉRICOS
                        st.markdown("---")
                        col_m1, col_m2 = st.columns(2)
                        with col_m1:
                            anios_mat = st.number_input("📅 Antigüedad máxima (Años transcurridos):", min_value=1, max_value=40, value=2, key="anios_m_in")
                        with col_m2:
                            min_ejemplares_mat = st.number_input("📚 Mínimo ejemplares en la Red:", min_value=1, max_value=100, value=3, key="min_ej_m_in")
                            limite_mat = st.number_input("🔢 Límite máximo de sugerencias:", min_value=5, max_value=500, value=100, step=5, key="limite_m_in")
                        
                        # 5. BOTÓN DE EJECUCIÓN Y RENDERIZADO DE RESULTADOS
                        if st.button("🔍 Extraer y Filtrar por Materias", type="primary", use_container_width=True):
                            with st.spinner(f"Analizando títulos de la Red para la selección temática..."):
                                
                                # Pasamos la lista de cadenas reales exactas que recopilamos
                                df_mat_resultado = obtener_recomendaciones_por_materia(
                                    conexion=conn,
                                    biblioteca=biblioteca_seleccionada,
                                    materias_seleccionadas=lista_materias_raw,  # <-- Enviamos la lista completa
                                    anios=anios_mat,
                                    min_ejemplares=min_ejemplares_mat,
                                    limite=limite_mat
                                )
                                
                                if not df_mat_resultado.empty:
                                    df_print = df_mat_resultado[[
                                        "id_sistema", "titulo", "autor", "editorial", "anio", "cdu", "isbn", "materias", "ejemplares", "bibliotecas"
                                    ]].copy()
                                    
                                    df_print.columns = [
                                        "ID Sistema", "Título", "Autor", "Editorial", "Año", "CDU", "ISBN", "Materias", "Ejemplares Red", "Bibliotecas Red"
                                    ]
                                    
                                    st.success(f"¡Éxito! Encontrados {len(df_print)} libros relevantes ausentes en tu centro.")
                                    st.dataframe(df_print, use_container_width=True, hide_index=True)
                                    
                                    csv_materias = df_print.to_csv(index=False, sep=';', encoding="utf-8-sig")
                                    nombre_archivo_limpio = sel_n1.lower().replace(" ", "_").replace("/", "-")
                                    
                                    st.download_button(
                                        label=f"📥 Descargar Recomendaciones (CSV)",
                                        data=csv_materias,
                                        file_name=f"rec_materias_{nombre_archivo_limpio}.csv",
                                        mime="text/csv",
                                        key="btn_dl_mat"
                                    )
                                else:
                                    st.info(f"ℹ️ No se detectan títulos ausentes para esta selección bajo los filtros actuales.")

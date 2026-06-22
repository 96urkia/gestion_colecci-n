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
# CONFIGURACIÓN DE BASE DE DATOS (CORREGIDA)
# ==========================================
DB_PATH = "gestion_coleccion.db"
DB_URL = "https://www.dropbox.com/scl/fi/pj1zlttvrb0g3deki1p3n/bibliotecas_navarra1.db?rlkey=ougwwguuucdjdsn2y47dm5gwm&st=9ctsqgy1&dl=1" 

@st.cache_resource
def obtener_conexion_db():
    debe_descargar = False
    if not os.path.exists(DB_PATH):
        debe_descargar = True
    elif os.path.getsize(DB_PATH) < 10000:  
        os.remove(DB_PATH)  
        debe_descargar = True

    if debe_descargar:
        with st.spinner("Descargando base de datos de la colección (500MB)... Esto puede tardar un minuto la primera vez."):
            try:
                urllib.request.urlretrieve(DB_URL, DB_PATH)
                st.toast("¡Base de datos descargada con éxito!", icon="📥")
            except Exception as e:
                st.error(f"Error crítico al descargar la base de datos desde Dropbox: {e}")
                return None
                
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        return conn
    except Exception as e:
        st.error(f"Error al conectar con el archivo SQLite: {e}")
        return None

# Inicializar la conexión
conn = obtener_conexion_db()

# --- FUNCIÓN PARA RECOMENDACIONES --

def obtener_recomendaciones_automaticas(conexion, bibliotecas, limite=50):
    """
    Recomienda libros populares en Navarra que NO tiene la(s) biblioteca(s) indicada(s).
    - bibliotecas: puede ser un string ("Monteagudo") o una lista de strings.
    """
    
    # Normalizar entrada a lista
    if isinstance(bibliotecas, str):
        bibliotecas = [bibliotecas]
    elif not isinstance(bibliotecas, (list, tuple)):
        st.error(f"❌ 'bibliotecas' debe ser texto o lista. Recibí: {type(bibliotecas)}")
        return pd.DataFrame()
    
    if not bibliotecas:
        st.error("❌ Debes indicar al menos una biblioteca.")
        return pd.DataFrame()
    
    # Placeholder para múltiples valores
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
        # Parámetros: primero las bibliotecas, luego el límite
        params = [b.upper().strip() for b in bibliotecas] + [int(limite)]
        
        df = pd.read_sql_query(query, conexion, params=params)
        
        if df.empty:
            st.warning(f"⚠️ No se encontraron recomendaciones. La(s) biblioteca(s) podrían tener casi todo el catálogo.")
        else:
            bib_text = ", ".join(bibliotecas)
            st.success(f"✅ {len(df)} recomendaciones cargadas (excluyendo {bib_text})")
        
        return df
        
    except Exception as e:
        st.error(f"❌ Error en la consulta SQL: {str(e)}")
        return pd.DataFrame()

@st.cache_data(ttl=1800, hash_funcs={sqlite3.Connection: lambda _: None})
def obtener_recomendaciones_por_cdu(conexion, bibliotecas_str, limite_por_cdu=10):

    if not bibliotecas_str:
        return pd.DataFrame()

    # Convertir a lista
    bibliotecas = [
        b.strip().upper()
        for b in bibliotecas_str.split("||")
        if b.strip()
    ]

    if not bibliotecas:
        return pd.DataFrame()

    placeholders = ",".join(["?"] * len(bibliotecas))

    query = f"""
    SELECT
        l.id_sistema,
        l.titulo,
        l.autor,
        l.anio,
        l.cdu,
        SUBSTR(COALESCE(l.cdu,''),1,3) AS cdu_base,
        COUNT(e.id) AS ejemplares,
        COUNT(DISTINCT e.biblioteca) AS bibliotecas
    FROM libros l
    JOIN ejemplares e
        ON l.id_sistema = e.id_sistema
    WHERE l.id_sistema NOT IN (
        SELECT DISTINCT id_sistema
        FROM ejemplares
        WHERE UPPER(TRIM(biblioteca)) IN ({placeholders})
    )
    GROUP BY
        l.id_sistema,
        l.titulo,
        l.autor,
        l.anio,
        l.cdu
    """

    try:
        df = pd.read_sql_query(
            query,
            conexion,
            params=bibliotecas
        )

        if df.empty:
            return pd.DataFrame()

        # Puntuación
        df["score"] = (
            df["bibliotecas"] * 10
            + df["ejemplares"]
        )

        # Evitar CDU vacías
        df["cdu_base"] = (
            df["cdu_base"]
            .fillna("SIN")
            .astype(str)
        )

        # Top N por CDU
        resultado = []

        for _, grupo in df.groupby("cdu_base"):
            top = grupo.sort_values(
                "score",
                ascending=False
            ).head(limite_por_cdu)

            resultado.append(top)

        if resultado:
            return pd.concat(resultado).reset_index(drop=True)

        return pd.DataFrame()

    except Exception as e:
        st.error(f"Error SQL: {e}")
        st.exception(e)
        return pd.DataFrame()




# ==========================================
# BACKEND Y FUNCIÓN DE PROCESAMIENTO
# ==========================================
BIBLIOTECAS = {
    "Monteagudo": 1100,
}

@st.cache_data
def procesar_datos(topo_bytes, nunca_bytes, mas2_bytes, catalogo_bytes, tipo_analisis, num_caracteres):
    if not topo_bytes or not catalogo_bytes:
        return None, 0
    
    # 1. Lectura y Extracción del Archivo Topográfico
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

    # 2. Catálogo y extracción de años
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

    # 3. Cruce de datos
    df_final = df_topo[df_topo['record_id'].isin(year_dict.keys())].copy()
    df_final['year'] = df_final['record_id'].map(year_dict)

    # 4. Inyección de Préstamos
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

    # 5. Clasificación semántica de la CDU
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
            if match_inf:
                return f"{match_inf.group(1)} (Infantil)"
            
            if re.search(r'\bJN\b', s): return "JN (Juvenil)"
            if re.search(r'\bN\s', s): return "Ficción / Narrativa"
            if re.search(r'\bP\s', s): return "Poesía"
            if re.search(r'\bT\s', s): return "Teatro"
            
            m = re.match(r'^(\d)', s)
            if m:
                cats = {
                    '0':'0 - General', '1':'1 - Filosofía', '2':'2 - Religión',
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

st.markdown('<div class="main-title">📚 Analizador Interactivo de Fondos</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Herramienta de soporte para expurgo, gestión de colecciones y análisis estratégico</div>', unsafe_allow_html=True)

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
        st.header("⚙️ 3. Configuración")
        tipo_analisis = st.selectbox(
            "Método de agrupación del tejuelo/CDU:",
            ["Clasificación Mixta Estándar (CDU + Letras)", "Solo Dígitos Iniciales de la CDU", "Longitud Fija (Primeros caracteres)"]
        )
        num_caracteres = st.slider("Caracteres a extraer:", 1, 10, 3) if tipo_analisis == "Longitud Fija (Primeros caracteres)" else None

        st.markdown("---")
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
# PANEL CENTRAL: CUADRO DE MANDO EN PESTAÑAS
# ==========================================

if st.session_state['analizado'] and st.session_state['resultado'] is not None:
    df_completo, huerfanos = st.session_state['resultado']
    
    total_docs = len(df_completo)
    pct_prestados = (df_completo['prestado'].sum() / total_docs * 100) if total_docs > 0 else 0
    edad_media = df_completo['year'].mean()
    docs_por_habitante = total_docs / poblacion_atendida if poblacion_atendida > 0 else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📖 Total Volumenes", f"{total_docs:,}")
    m2.metric("🪪 Índice de Circulación", f"{pct_prestados:.1f}%")
    m3.metric("📅 Edad Media del Fondo", f"{int(edad_media)} u." if not np.isnan(edad_media) else "N/A")
    m4.metric("👥 Docs por Habitante", f"{docs_por_habitante:.2f}")
    
    if huerfanos > 0:
        st.caption(f"ℹ️ Se han omitido {huerfanos} registros del topográfico por no tener correspondencia en el catálogo.")

    st.markdown("---")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Distribución y Uso", 
        "📚 Análisis por Categorías", 
        "🔎 Análisis exhaustivo por CDU", 
        "📋 Explorador de Colección",
        "🎯 Recomendaciones por CDU" # ← Nueva pestaña
    ])

    with tab1:
        st.subheader("⚖️ Diagnóstico de la Colección según Pautas Oficiales")
        
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
            if total_docs < 2500:
                st.error(f"🚨 **Alerta de Mínimo Absoluto:** IFLA establece un suelo de 2.500 obras. Tu colección cuenta con **{total_docs:,}**.")
            elif total_docs < pauta_min:
                st.warning(f"⚠️ **Déficit de Volumen:** Se recomiendan entre {pauta_min:,} y {pauta_max:,} documentos. Tienes **{total_docs:,}**.")
            elif total_docs > pauta_max:
                st.info(f"ℹ️ **Colección Sobredimensionada:** Rango óptimo: {pauta_min:,} a {pauta_max:,}. Tienes **{total_docs:,}**.")
            else:
                st.success(f"✅ **Volumen Óptimo:** Tu colección de **{total_docs:,}** volúmenes cumple el estándar.")

        with col_al2:
            if docs_por_habitante < pauta_hab:
                st.warning(f"⚠️ **Ratio por Habitante Bajo:** **{docs_por_habitante:.2f}** doc./hab. El mínimo es **{pauta_hab}**.")
            elif total_docs > pauta_max:
                st.info(f"ℹ️ **Ratio Anómalamente Elevado:** **{docs_por_habitante:.2f}** doc./hab. Supera la recomendación de **{pauta_hab}**.")
            else:
                st.success(f"✅ **Ratio por Habitante Óptimo:** **{docs_por_habitante:.2f}** doc./hab., cumpliendo el mínimo de **{pauta_hab}**.")

        st.write("#### 📊 Distribución Macroscópica del Fondo")
        def clasificar_macro(cat):
            c = str(cat).lower()
            if "dvd" in c or "audiovisual" in c: return "Audiovisuales/Multimedia"
            elif "infantil" in c or "juvenil" in c or "jn" in c or "ic" in c or "ip" in c or "it" in c: return "Infantil/Juvenil"
            else: return "Adultos"

        df_completo['macro_seccion'] = df_completo['categoria'].apply(clasificar_macro)
        macro_counts = df_completo['macro_seccion'].value_counts()
        
        pct_adultos = (macro_counts.get("Adultos", 0) / total_docs * 100) if total_docs > 0 else 0
        pct_infantil = (macro_counts.get("Infantil/Juvenil", 0) / total_docs * 100) if total_docs > 0 else 0
        pct_audio = (macro_counts.get("Audiovisuales/Multimedia", 0) / total_docs * 100) if total_docs > 0 else 0

        tabla_macro = pd.DataFrame({
            "Macro-Sección": ["Adultos", "Infantil/Juvenil", "Audiovisuales/Multimedia"],
            "Pauta Oficial": ["65.0%", "20.0%", "15.0%"],
            "Tu Biblioteca": [f"{pct_adultos:.1f}%", f"{pct_infantil:.1f}%", f"{pct_audio:.1f}%"],
            "Desviación": [f"{pct_adultos - 65:.1f}%", f"{pct_infantil - 20:.1f}%", f"{pct_audio - 15:.1f}%"]
        })
        st.dataframe(tabla_macro, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("📈 Nivel de rotación física")
        status_map = {0: 'Nunca prestado', 1: 'Prestado', 2: 'Muy prestado'}
        status_counts = df_completo['prestamos'].map(status_map).value_counts().reset_index()
        status_counts.columns = ['Estado', 'Cantidad']
        fig_pie = px.pie(status_counts, values='Cantidad', names='Estado', hole=0.4, color_discrete_sequence=px.colors.qualitative.Safe)
        st.plotly_chart(fig_pie, use_container_width=True)
        
        st.markdown("---")
        st.subheader("⏳ Cronología de Ediciones")
        if not df_completo['year'].dropna().empty:
            fig_hist = px.histogram(df_completo, x='year', nbins=25, labels={'year': 'Año de Publicación', 'count': 'Volúmenes'}, color_discrete_sequence=['#1E3A8A'])
            st.plotly_chart(fig_hist, use_container_width=True)

    with tab2:
        st.subheader("📊 Análisis de Volumen de Fondos por Categorías Generales")
        
        cat_counts = df_completo['categoria'].value_counts().reset_index()
        cat_counts.columns = ['Categoría', 'Volúmenes']
        fig_bar = px.bar(cat_counts, x='Volúmenes', y='Categoría', orientation='h', text='Volúmenes', color='Volúmenes', color_continuous_scale=px.colors.sequential.Blugrn)
        fig_bar.update_layout(yaxis={'categoryorder':'total ascending'}, height=500)
        st.plotly_chart(fig_bar, use_container_width=True)
        
        st.markdown("---")
        st.subheader("🔍 Desglose Métrico por Sección")
        
        tabla_cdu = df_completo.groupby('categoria').agg(
            Volumenes=('record_id', 'count'),
            Edad_Media=('year', lambda x: int(x.mean()) if not np.isnan(x.mean()) else np.nan),
            Prestados=('prestado', 'sum')
        ).reset_index()
        
        tabla_cdu['% de la Colección'] = (tabla_cdu['Volumenes'] / total_docs * 100).round(2)
        tabla_cdu['% Rotación Seccional'] = (tabla_cdu['Prestados'] / tabla_cdu['Volumenes'] * 100).round(2)
        
        tabla_cdu = tabla_cdu[['categoria', 'Volumenes', '% de la Colección', 'Edad_Media', '% Rotación Seccional']]
        tabla_cdu.columns = ['Categoría / CDU', 'Nº Volúmenes', '% de la Colección', 'Año Medio Edición', '% de Uso (Prestados)']
        
        def es_infantil(categoria):
            c = str(categoria).lower()
            return True if "infantil" in c or "juvenil" in c or c in ['i0', 'i1', 'i2', 'i3', 'jn'] else False

        es_inf = tabla_cdu['Categoría / CDU'].apply(es_infantil)
        tabla_infantil = tabla_cdu[es_inf].copy()
        tabla_adultos = tabla_cdu[~es_inf].copy()
        
        st.markdown("### 👥 Colección de Adultos")
        st.dataframe(tabla_adultos.sort_values(by='Nº Volúmenes', ascending=False), use_container_width=True, hide_index=True)
        
        st.markdown("### 🧒 Colección Infantil / Juvenil")
        st.dataframe(tabla_infantil.sort_values(by='Nº Volúmenes', ascending=False), use_container_width=True, hide_index=True)

    with tab3:
        st.subheader("🔎 Análisis por secciones (Jerarquía)")
        
        def convertir_a_csv(df):
            df_export = pd.DataFrame()
            df_export['codigo de barras'] = df['record_id'] if 'record_id' in df.columns else np.nan
            df_export['cdu'] = df['signatura_real'] if 'signatura_real' in df.columns else ""
            df_export['titulo'] = df['titulo'] if 'titulo' in df.columns else ""
            df_export['autor'] = "No detectado"
            
            if 'prestado' in df.columns:
                df_export['prestamo'] = df['prestado'].map({True: 'yes', False: 'not'})
            else:
                df_export['prestamo'] = 'not'
                
            df_export['año'] = df['year'] if 'year' in df.columns else np.nan
            return df_export.to_csv(index=False, sep=';', encoding='utf-8-sig')
        
        def mostrar_tabla_promedios(df_sub, total_coleccion):
            avg_year = int(df_sub['year'].mean()) if not df_sub['year'].dropna().empty else "N/A"
            pct_uso = (df_sub['prestado'].sum() / len(df_sub) * 100) if len(df_sub) > 0 else 0
            pct_col = (len(df_sub) / total_coleccion * 100) if total_coleccion > 0 else 0
            
            df_promedios = pd.DataFrame([{
                "Volúmenes": len(df_sub),
                "Año Promedio": avg_year,
                "% Uso (Préstamos)": f"{pct_uso:.2f}%",
                "% sobre Total Colección": f"{pct_col:.2f}%"
            }])
            st.dataframe(df_promedios, use_container_width=True, hide_index=True)
        
        def generar_seccion_resumen(df_sub, nombre_nivel, ruta_completa):
            if df_sub.empty: return
            
            unique_hash = hash(tuple(df_sub.index.tolist()))
            st.download_button(
                label=f"📥 Descargar CSV: {nombre_nivel}",
                data=convertir_a_csv(df_sub),
                file_name=f"export_{str(nombre_nivel).replace(' ', '_')[:20]}.csv",
                mime="text/csv",
                key=f"dl_{ruta_completa}_{unique_hash}"
            )
        
        def obtener_prefijo_dinamico(sig, seccion, nivel):
            sig = str(sig).strip().upper()
            if not sig or sig == "NAN": 
                return "Sin clasificar"
        
            if seccion == "Adultos":
                if sig[0].isdigit():
                    match = re.match(r'^([0-9]+)', sig)
                    if match:
                        num = match.group(1)
                        return num[:min(nivel, len(num))]
                if sig.startswith('('):
                    match = re.match(r'^(\([0-9]+\))', sig)
                    if match: return match.group(1)
                match = re.match(r'^([A-Za-z]+)', sig)
                if match: return match.group(1)
                return sig[:nivel]
                
            else: 
                match_edad = re.match(r'^(I[0-3]|JN|IJ|J)(?:\s|$)', sig)
                if match_edad:
                    return match_edad.group(1)
                
                match_conoc = re.match(r'^I\s+([0-9\(A-Z].*)', sig)
                if match_conoc:
                    cdu_interna = match_conoc.group(1).strip()
                    if cdu_interna and cdu_interna[0].isdigit():
                        match = re.match(r'^([0-9]+)', cdu_interna)
                        if match:
                            num = match.group(1)
                            return f"I {num[:min(nivel, len(num))]}"
                    if cdu_interna.startswith('('):
                        match = re.match(r'^(\([0-9]+\))', cdu_interna)
                        if match: return f"I {match.group(1)}"
                    match = re.match(r'^([A-Za-z]+)', cdu_interna)
                    if match: return f"I {match.group(1)}"
                    return f"I {cdu_interna[:nivel]}"
                
                sig_limpia = re.sub(r'^(I\s+|I/|IJ|JN|I-?)', '', sig).strip()
                if sig_limpia and sig_limpia[0].isdigit():
                    match = re.match(r'^([0-9]+)', sig_limpia)
                    if match:
                        num = match.group(1)
                        return num[:min(nivel, len(num))]
                return sig[:nivel]
        
        cdu_busqueda = st.text_input(
            "🔍 Buscador exhaustivo por prefijo CDU / Signatura (ej. 94(460.14), 82-3):",
            value=""
        ).strip().upper()
        
        df_jerarquia = df_completo.copy()
        
        if cdu_busqueda:
            df_jerarquia = df_jerarquia[
                df_jerarquia['signatura_real'].astype(str).str.strip().str.upper().str.startswith(cdu_busqueda)
            ]
            
            if not df_jerarquia.empty:
                st.markdown(f"### 📊 Indicadores del fondo filtrado por: `{cdu_busqueda}`")
                mostrar_tabla_promedios(df_jerarquia, total_docs)
                generar_seccion_resumen(df_jerarquia, f"Resultado {cdu_busqueda}", f"search_tab_{cdu_busqueda}")
                st.markdown("#### 🌳 Ubicación en el esquema jerárquico:")
            else:
                st.warning(f"⚠️ No se encontraron volúmenes que comiencen exactamente con el prefijo '{cdu_busqueda}' en el archivo.")
        
        if not df_jerarquia.empty:
            df_jerarquia['seccion'] = df_jerarquia['signatura_real'].apply(
                lambda x: "Infantil / Juvenil" if re.match(r'^(I|IJ|JN)', str(x).upper()) else "Adultos"
            )
            
            tabs = st.tabs(["👥 Adultos", "🧸 Infantil / Juvenil"])
            for i, sec in enumerate(["Adultos", "Infantil / Juvenil"]):
                with tabs[i]:
                    df_sec = df_jerarquia[df_jerarquia['seccion'] == sec].copy()
                    
                    if df_sec.empty:
                        st.info(f"No hay registros en la sección {sec} para el criterio actual.")
                        continue
        
                    df_sec['Nivel_1'] = df_sec['signatura_real'].apply(lambda x: obtener_prefijo_dinamico(x, sec, 1))
                    nodos_l1 = sorted(df_sec['Nivel_1'].unique())
                    
                    for n1 in nodos_l1:
                        df_n1 = df_sec[df_sec['Nivel_1'] == n1].copy()
                        
                        df_n1['Nivel_2'] = df_n1['signatura_real'].apply(lambda x: obtener_prefijo_dinamico(x, sec, 2))
                        nodos_l2 = sorted(df_n1['Nivel_2'].unique())
                        
                        if len(nodos_l2) == 1 and nodos_l2[0] == n1:
                            with st.expander(f"📚 {n1}"):
                                generar_seccion_resumen(df_n1, n1, f"{sec}_L1_{n1}")
                                mostrar_tabla_promedios(df_n1, total_docs)
                        
                        else:
                            with st.expander(f"🗄️ Nivel Principal: {n1} ({len(df_n1)} volúmenes)"):
                                for n2 in nodos_l2:
                                    df_n2 = df_n1[df_n1['Nivel_2'] == n2].copy()
                                    
                                    df_n2['Nivel_3'] = df_n2['signatura_real'].apply(lambda x: obtener_prefijo_dinamico(x, sec, 3))
                                    nodos_l3 = sorted(df_n2['Nivel_3'].unique())
                                    
                                    with st.expander(f"📁 Subnivel: {n2}"):
                                        generar_seccion_resumen(df_n2, n2, f"{sec}_L2_{n2}")
                                        
                                        if len(nodos_l3) == 1 and nodos_l3[0] == n2:
                                            mostrar_tabla_promedios(df_n2, total_docs)
                                        else:
                                            for n3 in nodos_l3:
                                                df_n3 = df_n2[df_n2['Nivel_3'] == n3]
                                                st.markdown(f"**📖 Específico: {n3}**")
                                                mostrar_tabla_promedios(df_n3, total_docs)
                                st.divider()

    with tab4:
        st.header("📚 Recomendaciones de Adquisición Automáticas")
        st.write("Libros más presentes en la Red de Bibliotecas de Navarra que faltan en tu colección:")
        
        if st.session_state['analizado'] and st.session_state['resultado'] is not None:
            df_tu_biblioteca = st.session_state['resultado'][0] 
            mis_libros_ids = df_tu_biblioteca['record_id'].tolist()
            
            with st.spinner("Calculando faltantes más populares..."):
                df_top_compras = obtener_recomendaciones_automaticas(conn, "Monteagudo", limite=20)
                
            if not df_top_compras.empty:
                st.dataframe(
                    df_top_compras,
                    column_config={
                        "record_id": "ID Registro",
                        "titulo": "Título del Libro",
                        "total_bibliotecas": "Nº Bibliotecas que lo tienen"
                    },
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No se pudieron cargar recomendaciones o tu biblioteca ya tiene todo el catálogo.")
        else:
            st.warning("⚠️ Primero debes cargar y analizar los archivos topográficos en la pestaña de inicio.")

    with tab5:
        st.subheader("🎯 Recomendaciones de adquisición estructuradas")

        if conn is None:
            st.error("No hay conexión con la base de datos")
        else:
            # Filtros interactivos globales en la parte superior de la pestaña
            col_filtros1, col_filtros2 = st.columns(2)
            with col_filtros1:
                limite_cdu = st.number_input(
                    "Máximo de recomendaciones por menú:",
                    min_value=1,
                    max_value=100,
                    value=10,
                    step=1,
                    key="limite_cdu_tab5"
                )
            with col_filtros2:
                anio_minimo = st.number_input(
                    "Año mínimo de publicación:",
                    min_value=1800,
                    max_value=2026,
                    value=2015,
                    step=1,
                    key="anio_minimo_tab5"
                )

            biblioteca = biblioteca_seleccionada.upper().strip()

            # Consulta SQL eficiente para extraer los libros y el histórico de sus tejuelos en la Red
            query = """
            SELECT
                l.id_sistema,
                l.titulo,
                l.autor,
                l.anio,
                l.cdu,
                COUNT(DISTINCT e.biblioteca) AS id_red_bibliotecas,
                GROUP_CONCAT(e.signatura, '||') AS todas_signaturas
            FROM libros l
            JOIN ejemplares e ON l.id_sistema = e.id_sistema
            WHERE l.id_sistema NOT IN (
                SELECT DISTINCT id_sistema
                FROM ejemplares
                WHERE UPPER(TRIM(biblioteca)) = ?
            )
            AND CAST(COALESCE(l.anio, 0) AS INTEGER) >= ?
            GROUP BY l.id_sistema, l.titulo, l.autor, l.anio, l.cdu
            HAVING id_red_bibliotecas > 0
            """

            with st.spinner("Filtrando y organizando el catálogo de la Red por secciones..."):
                df = pd.read_sql_query(query, conn, params=[biblioteca, int(anio_minimo)])

            if df.empty:
                st.warning("⚠️ No se encontraron recomendaciones con los filtros seleccionados.")
            else:
                # 1. Función interna para hilar fino con los tejuelos infantiles
                def clasificar_infantil(todas_sigs):
                    if not todas_sigs:
                        return None
                    
                    sigs = [s.strip().upper() for s in str(todas_sigs).split('||') if s.strip()]
                    
                    for sig in sigs:
                        # Edades estrictas (Sin espacio): I0, I1, I2, I3 o JN
                        match_edad = re.search(r'\b(I0|I1|I2|I3|JN)\b', sig)
                        if match_edad:
                            return match_edad.group(1)
                        
                        # Materias estrictas (Con espacio): I 0, I 1, etc.
                        match_mat = re.search(r'\bI\s+([0-9])\b', sig)
                        if match_mat:
                            return f"I CDU {match_mat.group(1)}"
                        
                        # Autocorrección de seguridad: si escribieron "I7" sin espacio, se fuerza a materia "I CDU 7"
                        match_typo = re.search(r'\bI([4-9])\b', sig)
                        if match_typo:
                            return f"I CDU {match_typo.group(1)}"
                            
                    return None

                # 2. Función matriz de clasificación (Actúa como embudo/filtro de ruido)
                def clasificar_libro(row):
                    cdu = str(row["cdu"]).strip().upper()
                    
                    # FILTRO INFANTIL: Obras que empiezan por 087.5
                    if cdu.startswith("087.5"):
                        cat_inf = clasificar_infantil(row.get("todas_signaturas", ""))
                        if cat_inf:
                            return "Infantil", cat_inf
                        return None, None # Si no tiene un tejuelo infantil reconocible, se descarta como ruido
                    
                    # FILTRO ADULTOS - FICCIÓN: Obras que empiezan por 821
                    if cdu.startswith("821"):
                        return "Adultos", "Ficción"
                    
                    # FILTRO ADULTOS - MATERIAS CDU: Mapeo estricto de las clases solicitadas
                    m = re.match(r'^(\d)', cdu)
                    if m:
                        digito = m.group(1)
                        if digito in ['0', '1', '2', '5', '6', '7', '8', '9']:
                            return "Adultos", f"CDU {digito}"
                    
                    return None, None # Cualquier otra cosa (CDU 3, CDU 4, vacíos...) se ignora por completo

                # Aplicamos las reglas al DataFrame
                resultados = df.apply(clasificar_libro, axis=1)
                df["subtab_destino"] = [r[0] for r in resultados]
                df["categoria_final"] = [r[1] for r in resultados]
                
                # Eliminación activa del ruido: nos quedamos solo con lo clasificado de forma válida
                df = df[df["subtab_destino"].notna()].copy()
                
                # Ordenación global por impacto en la Red (Nº de bibliotecas)
                df["score"] = df["id_red_bibliotecas"]
                df = df.sort_values("score", ascending=False)

                # Creamos las dos subpestañas solicitadas
                subtab_adultos, subtab_infantil = st.tabs(["👨‍💼 Sección Adultos", "👶 Sección Infantil"])

                # ==========================================
                # 1) SUBPESTAÑA: ADULTOS
                # ==========================================
                with subtab_adultos:
                    # Estructura fija y ordenada de los menús autorizados
                    menus_adultos = {
                        "Ficción": "📖 Ficción Adultos (821)",
                        "CDU 0": "📂 CDU 0 - Generalidades. Ciencia y Conocimiento",
                        "CDU 1": "📂 CDU 1 - Filosofía. Psicología",
                        "CDU 2": "📂 CDU 2 - Religión. Teología",
                        "CDU 5": "📂 CDU 5 - Ciencias Puras. Naturales",
                        "CDU 6": "📂 CDU 6 - Ciencias Aplicadas. Medicina. Tecnología",
                        "CDU 7": "📂 CDU 7 - Bellas Artes. Espectáculos. Deportes",
                        "CDU 8": "📂 CDU 8 - Lingüística. Filología. Literatura (Exc. Ficción)",
                        "CDU 9": "📂 CDU 9 - Geografía. Biografías. Historia"
                    }
                    
                    hay_adultos = False
                    for key_cat, titulo_expander in menus_adultos.items():
                        # Filtrar datos de la categoría concreta y aplicar el límite
                        df_grupo = df[(df["subtab_destino"] == "Adultos") & (df["categoria_final"] == key_cat)].head(limite_cdu)
                        
                        if not df_grupo.empty:
                            hay_adultos = True
                            with st.expander(f"{titulo_expander} ({len(df_grupo)} títulos sugeridos)"):
                                df_mostrar = df_grupo[["titulo", "autor", "anio", "cdu", "id_red_bibliotecas"]].copy()
                                df_mostrar.columns = ["Título", "Autor", "Año", "CDU Completa", "Nº Bibliotecas Red"]
                                
                                st.dataframe(df_mostrar, use_container_width=True, hide_index=True)
                                
                                # Botón de descarga de datos específico
                                csv = df_mostrar.to_csv(index=False, sep=';', encoding="utf-8-sig")
                                st.download_button(
                                    label=f"📥 Descargar CSV",
                                    data=csv,
                                    file_name=f"adultos_{key_cat.replace(' ', '_')}.csv",
                                    mime="text/csv",
                                    key=f"dl_adultos_{key_cat}"
                                )
                    if not hay_adultos:
                        st.info("ℹ️ No se encontraron recomendaciones para la sección de Adultos con los filtros actuales.")

                # ==========================================
                # 2) SUBPESTAÑA: INFANTIL
                # ==========================================
                with subtab_infantil:
                    # Estructura fija y ordenada de los menús autorizados (Edades + Materias)
                    menus_infantil = {
                        "I0": "👶 I0 - Prenatal / Bebeteca",
                        "I1": "🧸 I1 - Primeros Lectores (Hasta 6 años)",
                        "I2": "🎒 I2 - Lectores Iniciados (7-9 años)",
                        "I3": "🛡️ I3 - Lectores Experimentados (10-12 años)",
                        "JN": "⚡ JN - Juvenil",
                        "I CDU 0": "📚 I CDU 0 - Generalidades",
                        "I CDU 1": "📚 I CDU 1 - Filosofía y Psicología",
                        "I CDU 2": "📚 I CDU 2 - Religión",
                        "I CDU 3": "📚 I CDU 3 - Ciencias Sociales",
                        "I CDU 4": "📚 I CDU 4 - Lengua / Lingüística",
                        "I CDU 5": "📚 I CDU 5 - Ciencias Puras. Naturales",
                        "I CDU 6": "📚 I CDU 6 - Ciencias Aplicadas. Tecnología",
                        "I CDU 7": "📚 I CDU 7 - Bellas Artes. Deportes",
                        "I CDU 8": "📚 I CDU 8 - Literatura / Filología",
                        "I CDU 9": "📚 I CDU 9 - Geografía e Historia"
                    }
                    
                    hay_infantil = False
                    for key_cat, titulo_expander in menus_infantil.items():
                        # Filtrar datos de la categoría infantil concreta y aplicar el límite
                        df_grupo = df[(df["subtab_destino"] == "Infantil") & (df["categoria_final"] == key_cat)].head(limite_cdu)
                        
                        if not df_grupo.empty:
                            hay_infantil = True
                            with st.expander(f"{titulo_expander} ({len(df_grupo)} títulos sugeridos)"):
                                df_mostrar = df_grupo[["titulo", "autor", "anio", "cdu", "id_red_bibliotecas"]].copy()
                                df_mostrar.columns = ["Título", "Autor", "Año", "CDU Completa", "Nº Bibliotecas Red"]
                                
                                st.dataframe(df_mostrar, use_container_width=True, hide_index=True)
                                
                                # Botón de descarga de datos específico
                                csv = df_mostrar.to_csv(index=False, sep=';', encoding="utf-8-sig")
                                st.download_button(
                                    label=f"📥 Descargar CSV",
                                    data=csv,
                                    file_name=f"infantil_{key_cat.replace(' ', '_')}.csv",
                                    mime="text/csv",
                                    key=f"dl_infantil_{key_cat}"
                                )
                    if not hay_infantil:
                        st.info("ℹ️ No se encontraron recomendaciones para la sección Infantil con los filtros actuales.")



import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.express as px

# Configuración de la página
st.set_page_config(
    page_title="Analizador de Fondos de Biblioteca",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# BACKEND: DICCIONARIO DE BIBLIOTECAS
# ==========================================
BIBLIOTECAS = {
    "Monteagudo": 1100,
}

# Estilo personalizado
st.markdown("""
    <style>
    .main-title {
        font-size: 2.2rem;
        color: #1E3A8A;
        font-weight: bold;
        margin-bottom: 0.5rem;
    }
    .subtitle {
        font-size: 1.1rem;
        color: #4B5563;
        margin-bottom: 2rem;
    }
    div[data-testid="metric-container"] {
        background-color: #F3F4F6;
        border-radius: 0.5rem;
        padding: 1rem;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">Analizador Interactivo de Fondos de Biblioteca</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Herramienta de soporte para el expurgo, gestión de colecciones y análisis estratégico basado en datos de Absys.</div>', unsafe_allow_html=True)

# Variables de sesión para controlar el botón
if 'analizado' not in st.session_state:
    st.session_state['analizado'] = False

# ==========================================
# PÁGINA PRINCIPAL: SELECCIÓN Y CARGA DE DATOS
# ==========================================
st.header("🏢 1. Selección de Biblioteca y Carga de Archivos")

biblioteca_seleccionada = st.selectbox(
    "Selecciona la biblioteca para el análisis:",
    options=list(BIBLIOTECAS.keys()),
    help="Determina la biblioteca activa y carga su población atendida."
)
poblacion_atendida = BIBLIOTECAS[biblioteca_seleccionada]

col_up1, col_up2 = st.columns(2)

with col_up1:
    uploaded_topo = st.file_uploader("Archivo Topográfico (.txt) *Requerido*", type=["txt"], help="Listado topográfico exportado de Absys")
    uploaded_nunca = st.file_uploader("No Prestados (.txt)", type=["txt"], help="Listado de códigos/IDs que nunca se han prestado")

with col_up2:
    uploaded_mas2 = st.file_uploader("Más Prestados (.txt)", type=["txt"], help="Listado de códigos/IDs con más préstamos")
    uploaded_catalogo = st.file_uploader("Catálogo Completo (.txt) *Requerido*", type=["txt"], help="Catálogo general para cruce de IDs y extracción de años")

st.markdown("---")

# ==========================================
# BARRA LATERAL: CONFIGURACIÓN DE ANÁLISIS
# ==========================================
st.sidebar.header("⚙️ 2. Configuración de Análisis")

tipo_analisis = st.sidebar.selectbox(
    "Método de agrupación del tejuelo/CDU:",
    ["Clasificación Mixta Estándar (CDU + Letras)", "Solo Dígitos Iniciales de la CDU", "Longitud Fija (Primeros caracteres)"],
    help="Define cómo procesar el tejuelo para segmentar la colección."
)

if tipo_analisis == "Longitud Fija (Primeros caracteres)":
    num_caracteres = st.sidebar.slider("Número de caracteres a extraer:", min_value=1, max_value=10, value=3)
else:
    num_caracteres = None

st.sidebar.markdown("---")

if st.sidebar.button("🚀 Analizar Fondos", type="primary"):
    st.session_state['analizado'] = True

# ==========================================
# FUNCIÓN DE PROCESAMIENTO (CON CACHE)
# ==========================================
@st.cache_data
def procesar_datos(topo_bytes, nunca_bytes, mas2_bytes, catalogo_bytes, tipo_analisis, num_caracteres):
    if not topo_bytes or not catalogo_bytes:
        return None
        
    # 1. LECTURA DEL TOPOGRÁFICO
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
        data.append({"record_id": record_id, "signatura_real": signatura})
        
    df_topo = pd.DataFrame(data)
    if df_topo.empty: return None
    
    # Eliminamos duplicados iniciales por seguridad
    df_topo = df_topo.drop_duplicates(subset=['record_id'])

    # 2. LECTURA DEL CATÁLOGO Y EXTRACCIÓN DE AÑOS
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
            
    # 3. CRUCE ESTRICTO
    df_final = df_topo[df_topo['record_id'].isin(year_dict.keys())].copy()
    df_final['year'] = df_final['record_id'].map(year_dict)

    # 4. CRUCE DE PRÉSTAMOS
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

    # 5. CLASIFICACIÓN
    def clasificar_dinamico(sign):
        if not sign: return "Sin clasificar"
        s = str(sign).upper().strip()
        
        if tipo_analisis == "Clasificación Mixta Estándar (CDU + Letras)":
            if re.search(r'I[0-9]', s): return "Infantil / Juvenil"
            if re.search(r'\bN\s', s): return "Ficción / Narrativa"
            if re.search(r'\bP\s', s): return "Poesía"
            if re.search(r'\bT\s', s): return "Teatro"
            m = re.match(r'^(\d)', s)
            if m:
                cats = {
                    '0':'0-General','1':'1-Filosofía','2':'2-Religión',
                    '3':'3-Sociales','4':'4-Lingüística','5':'5-Ciencias',
                    '6':'6-Tecnología','7':'7-Arte/Deportes',
                    '8':'8-Literatura','9':'9-Historia'
                }
                return cats.get(m.group(1), "Otros")
            return "Otros"
            
        elif tipo_analisis == "Solo Dígitos Iniciales de la CDU":
            m = re.match(r'^(\d+)', s)
            if m: return f"CDU {m.group(1)[0]}"
            return "Ficción / Otros no numéricos"
            
        elif tipo_analisis == "Longitud Fija (Primeros caracteres)":
            return s[:num_caracteres]
            
        return "Otros"

    df_final['categoria'] = df_final['signatura_real'].apply(clasificar_dinamico)
    return df_final, len(df_topo) - len(df_final)

# ==========================================
# EJECUCIÓN SI SE HA PULSADO EL BOTÓN
# ==========================================
if st.session_state['analizado']:
    if not uploaded_topo or not uploaded_catalogo:
        st.warning("⚠️ Por favor, sube el 'Archivo Topográfico' y el 'Catálogo Completo'. Ambos son necesarios para realizar el cruce estricto de IDs.")
    else:
        topo_bytes = uploaded_topo.getvalue()
        nunca_bytes = uploaded_nunca.getvalue() if uploaded_nunca else None
        mas2_bytes = uploaded_mas2.getvalue() if uploaded_mas2 else None
        catalogo_bytes = uploaded_catalogo.getvalue()
        
        with st.spinner("Procesando y cruzando los fondos de la colección con el catálogo..."):
            resultado = procesar_datos(topo_bytes, nunca_bytes, mas2_bytes, catalogo_bytes, tipo_analisis, num_caracteres)
            
        if resultado is not None:
            df_completo, huerfanos = resultado
            
            st.header(f"📊 Fotografía General: {biblioteca_seleccionada}")
            
            if huerfanos > 0:
                st.caption(f"ℹ️ *Nota: Se han excluido {huerfanos} registros 'huérfanos' presentes en el topográfico pero no localizados en el catálogo general.*")
            
            st.markdown("---")
            
            # Cálculos globales
            total_docs = len(df_completo)
            pct_prestados = (df_completo['prestado'].sum() / total_docs) * 100 if total_docs > 0 else 0
            edad_media = df_completo['year'].mean()
            docs_por_habitante = total_docs / poblacion_atendida if poblacion_atendida > 0 else 0
            
            # ====================================================
            # FILA 1: INDICADORES CLAVE (Horizontal)
            # ====================================================
            st.markdown("#### 📌 Indicadores Clave")
            m1, m2, m3, m4, m5 = st.columns(5)
            
            m1.metric(label="📖 Total Docs.", value=f"{total_docs:,}")
            m2.metric(label="🪪 Docs. Prestados", value=f"{pct_prestados:.1f} %")
            m3.metric(label="📅 Edad Media", value=f"{int(edad_media)}" if not np.isnan(edad_media) else "N/A")
            m4.metric(label="👤 Pob. Atendida", value=f"{poblacion_atendida:,}")
            m5.metric(label="📖👤 Docs/Habitante", value=f"{docs_por_habitante:.2f}")
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # ====================================================
            # FILA 2: USO DE LA COLECCIÓN
            # ====================================================
            st.markdown("#### 📈 Uso de la Colección")
            status_counts = df_completo['prestamos'].map({0: 'Nunca prestado', 1: 'Prestado estándar', 2: 'Muy prestado'}).value_counts().reset_index()
            status_counts.columns = ['Estado', 'Cantidad']
            fig_pie = px.pie(status_counts, values='Cantidad', names='Estado', 
                             color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            fig_pie.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=400)
            st.plotly_chart(fig_pie, use_container_width=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # ====================================================
            # FILA 3: ENVEJECIMIENTO DEL FONDO
            # ====================================================
            st.markdown("#### ⏳ Envejecimiento del Fondo")
            if not df_completo['year'].dropna().empty:
                fig_hist = px.histogram(df_completo, x='year', nbins=30,
                                        labels={'year': 'Año de Edición', 'count': 'Nº de Documentos'},
                                        color_discrete_sequence=['#2563EB'])
                fig_hist.update_layout(showlegend=False, margin=dict(t=20, b=20, l=20, r=20), height=400)
                st.plotly_chart(fig_hist, use_container_width=True)
            else:
                st.info("Sube el archivo de catálogo para ver la distribución temporal.")
                    
else:
    st.info("👋 ¡Bienvenido/a al Analizador Interactivo de Fondos!")
    st.markdown("""
    ### Instrucciones:
    1. Selecciona tu **Biblioteca** y carga los archivos `.txt` requeridos arriba en la **página principal**.
    2. Modifica el método de agrupación en la **barra lateral** (si lo deseas).
    3. Pulsa el botón azul **🚀 Analizar Fondos** ubicado en la barra lateral para ver los indicadores y gráficos clave.
    """)

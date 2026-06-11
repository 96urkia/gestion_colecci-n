import streamlit as st
import pandas as pd
import numpy as np
import re
import plotly.express as px

# ==========================================
# CONFIGURACIÓN DE PÁGINA Y ESTADO
# ==========================================
st.set_page_config(
    page_title="Analizador de Fondos de Biblioteca",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inicializar variables de sesión si no existen
if 'analizado' not in st.session_state:
    st.session_state['analizado'] = False
if 'resultado' not in st.session_state:
    st.session_state['resultado'] = None

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
    
    # 1. Lectura Topográfico
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

    # 3. Cruce
    df_final = df_topo[df_topo['record_id'].isin(year_dict.keys())].copy()
    df_final['year'] = df_final['record_id'].map(year_dict)

    # 4. Préstamos
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

    # 5. Clasificación
    def clasificar_dinamico(sign):
        if not sign: 
            return "Sin clasificar"
        s = str(sign).upper().strip()
        
        if tipo_analisis == "Clasificación Mixta Estándar (CDU + Letras)":
            if re.search(r'I[0-9]', s): return "Infantil / Juvenil"
            if re.search(r'\bN\s', s): return "Ficción / Narrativa"
            if re.search(r'\bP\s', s): return "Poesía"
            if re.search(r'\bT\s', s): return "Teatro"
            m = re.match(r'^(\d)', s)
            if m:
                cats = {'0':'0-General','1':'1-Filosofía','2':'2-Religión','3':'3-Sociales',
                        '4':'4-Lingüística','5':'5-Ciencias','6':'6-Tecnología',
                        '7':'7-Arte/Deportes','8':'8-Literatura','9':'9-Historia'}
                return cats.get(m.group(1), "Otros")
            return "Otros"
            
        elif tipo_analisis == "Solo Dígitos Iniciales de la CDU":
            m = re.match(r'^(\d+)', s)
            return f"CDU {m.group(1)[0]}" if m else "Ficción / Otros"
            
        elif tipo_analisis == "Longitud Fija (Primeros caracteres)":
            return s[:num_caracteres]
        
        return "Otros"

    df_final['categoria'] = df_final['signatura_real'].apply(clasificar_dinamico)
    
    return df_final, len(df_topo) - len(df_final)

# ==========================================
# ESTILOS Y CABECERA
# ==========================================
st.markdown("""
    <style>
    .main-title {
        font-size: 2.3rem;
        color: #1E3A8A;
        font-weight: bold;
        margin-bottom: 0.3rem;
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

st.markdown('<div class="main-title">📚 Analizador Interactivo de Fondos</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Herramienta de soporte para expurgo, gestión de colecciones y análisis estratégico</div>', unsafe_allow_html=True)

# ==========================================
# SIDEBAR
# ==========================================
with st.sidebar:
    st.header("🏢 1. Selección de Biblioteca")
    biblioteca_seleccionada = st.selectbox(
        "Biblioteca:",
        options=list(BIBLIOTECAS.keys())
    )
    poblacion_atendida = BIBLIOTECAS[biblioteca_seleccionada]

    st.markdown("---")

    # MODO CONFIGURACIÓN: Mostrar campos de subida si no se ha analizado aún
    if not st.session_state['analizado']:
        st.header("📂 2. Carga de Archivos")
        
        uploaded_topo = st.file_uploader("Archivo Topográfico (.txt) *Requerido*", 
                                       type=["txt"], help="Listado topográfico exportado de Absys")
        uploaded_catalogo = st.file_uploader("Catálogo Completo (.txt) *Requerido*", 
                                           type=["txt"], help="Catálogo general para extracción de años")
        
        uploaded_nunca = st.file_uploader("No Prestados (.txt)", 
                                        type=["txt"], help="Opcional")
        uploaded_mas2 = st.file_uploader("Más Prestados (.txt)", 
                                       type=["txt"], help="Opcional")

        st.markdown("---")
        st.header("⚙️ 3. Configuración de Análisis")
        tipo_analisis = st.selectbox(
            "Método de agrupación del tejuelo/CDU:",
            ["Clasificación Mixta Estándar (CDU + Letras)", 
             "Solo Dígitos Iniciales de la CDU", 
             "Longitud Fija (Primeros caracteres)"]
        )

        num_caracteres = None
        if tipo_analisis == "Longitud Fija (Primeros caracteres)":
            num_caracteres = st.slider("Número de caracteres a extraer:", 
                                     min_value=1, max_value=10, value=3)

        st.markdown("---")
        if st.button("🚀 Analizar Fondos", type="primary", use_container_width=True):
            if not uploaded_topo or not uploaded_catalogo:
                st.error("⚠️ Debes subir **Archivo Topográfico** y **Catálogo Completo**")
            else:
                with st.spinner("Procesando fondos y cruzando con catálogo..."):
                    resultado = procesar_datos(
                        uploaded_topo.getvalue(),
                        uploaded_nunca.getvalue() if uploaded_nunca else None,
                        uploaded_mas2.getvalue() if uploaded_mas2 else None,
                        uploaded_catalogo.getvalue(),
                        tipo_analisis,
                        num_caracteres
                    )
                    
                    if resultado:
                        st.session_state['resultado'] = resultado
                        st.session_state['analizado'] = True
                        st.rerun() # Refresca la app para ocultar la barra lateral
    
    # MODO RESULTADOS: Archivos ocultos, mostrar botón para volver atrás
    else:
        st.success("✅ Archivos procesados con éxito.")
        st.info("La carga de archivos está oculta para dejar más espacio al análisis.")
        
        if st.button("🔄 Volver a subir archivos", use_container_width=True):
            st.session_state['analizado'] = False
            st.session_state['resultado'] = None
            st.rerun()

# ==========================================
# PANEL CENTRAL: RESULTADOS
# ==========================================
if st.session_state['analizado'] and st.session_state['resultado'] is not None:
    df_completo, huerfanos = st.session_state['resultado']
    
    st.header(f"📊 Fotografía General: **{biblioteca_seleccionada}**")
    if huerfanos > 0:
        st.caption(f"ℹ️ Se excluyeron {huerfanos} registros huérfanos (no encontrados en el catálogo)")

    # Métricas
    total_docs = len(df_completo)
    pct_prestados = (df_completo['prestado'].sum() / total_docs * 100) if total_docs > 0 else 0
    edad_media = df_completo['year'].mean()
    docs_por_habitante = total_docs / poblacion_atendida if poblacion_atendida > 0 else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("📖 Total Documentos", f"{total_docs:,}")
    m2.metric("🪪 Prestados", f"{pct_prestados:.1f}%")
    m3.metric("📅 Edad Media", f"{int(edad_media)}" if not np.isnan(edad_media) else "N/A")
    m4.metric("👥 Población Atendida", f"{poblacion_atendida:,}")
    m5.metric("📖/👤 Docs por habitante", f"{docs_por_habitante:.2f}")

    # Gráficos
    st.markdown("---")
    st.subheader("📈 Uso de la Colección")
    status_map = {0: 'Nunca prestado', 1: 'Prestado', 2: 'Muy prestado'}
    status_counts = df_completo['prestamos'].map(status_map).value_counts().reset_index()
    status_counts.columns = ['Estado', 'Cantidad']
    
    fig_pie = px.pie(status_counts, values='Cantidad', names='Estado',
                   color_discrete_sequence=px.colors.qualitative.Pastel)
    fig_pie.update_traces(textposition='inside', textinfo='percent+label')
    st.plotly_chart(fig_pie, use_container_width=True)

    st.markdown("---")
    st.subheader("⏳ Envejecimiento del Fondo")
    if not df_completo['year'].dropna().empty:
        fig_hist = px.histogram(df_completo, x='year', nbins=30,
                              labels={'year': 'Año de Edición', 'count': 'Cantidad'})
        fig_hist.update_layout(height=400)
        st.plotly_chart(fig_hist, use_container_width=True)
    else:
        st.info("No hay información de años disponible.")

else:
    # Mensaje inicial en la pantalla principal
    st.info("👉 Usa el **menú lateral** para cargar los archivos y pulsar **Analizar Fondos**.")

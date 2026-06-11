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
# Aquí puedes ir ampliando el listado en el futuro siguiendo el mismo formato
BIBLIOTECAS = {
    "Monteagudo": 1100,
    # "Ejemplo Biblioteca 2": 5000,
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

# Selector de biblioteca basado en el diccionario del Backend
biblioteca_seleccionada = st.selectbox(
    "Selecciona la biblioteca para el análisis:",
    options=list(BIBLIOTECAS.keys()),
    help="Determina la biblioteca activa y carga su población atendida."
)
# Extraemos el valor del diccionario según la selección
poblacion_atendida = BIBLIOTECAS[biblioteca_seleccionada]

# Distribución de la carga de archivos en 2 columnas en la página principal
col_up1, col_up2 = st.columns(2)

with col_up1:
    uploaded_topo = st.file_uploader("Archivo Topográfico (.txt) *Requerido*", type=["txt"], help="Listado topográfico exportado de Absys")
    uploaded_nunca = st.file_uploader("No Prestados (.txt)", type=["txt"], help="Listado de códigos/IDs que nunca se han prestado")

with col_up2:
    uploaded_mas2 = st.file_uploader("Más Prestados (.txt)", type=["txt"], help="Listado de códigos/IDs con más préstamos")
    uploaded_catalogo = st.file_uploader("Catálogo Completo (.txt)", type=["txt"], help="Catálogo general para la extracción de años")

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

# EL BOTÓN AZUL DE ANÁLISIS (Se mantiene en el sidebar para iniciar la acción)
if st.sidebar.button("🚀 Analizar Fondos", type="primary"):
    st.session_state['analizado'] = True

# ==========================================
# FUNCIÓN DE PROCESAMIENTO (CON CACHE)
# ==========================================
@st.cache_data
def procesar_datos(topo_bytes, nunca_bytes, mas2_bytes, catalogo_bytes, tipo_analisis, num_caracteres):
    if not topo_bytes:
        return None
        
    topo_text = topo_bytes.decode('utf-8', errors='replace')
    data = []
    for line in topo_text.split('\n'):
        line = line.strip()
        if not line or re.search(r'^(LISTADO|Signatura|-----)', line):
            continue
        match = re.search(r'\b(\d{7,})\b', line)
        if not match:
            continue
        record_id = int(match.group(1))
        sign_match = re.search(r'(.+?)\s+84\s+[A-Z]{2}', line)
        signatura = sign_match.group(1).strip() if sign_match else line
        data.append({"record_id": record_id, "signatura_real": signatura})
        
    df = pd.DataFrame(data)
    if df.empty: return None

    df['prestamos'] = 1
    
    if nunca_bytes:
        nunca_text = nunca_bytes.decode('utf-8', errors='replace')
        nunca_ids = {int(x) for x in re.findall(r'\b\d{7,}\b', nunca_text)}
        df.loc[df['record_id'].isin(nunca_ids), 'prestamos'] = 0
        
    if mas2_bytes:
        mas2_text = mas2_bytes.decode('utf-8', errors='replace')
        mas2_ids = {int(x) for x in re.findall(r'\b\d{7,}\b', mas2_text)}
        df.loc[df['record_id'].isin(mas2_ids), 'prestamos'] = 2
        
    df['prestado'] = df['prestamos'] > 0

    if catalogo_bytes:
        cat_text = catalogo_bytes.decode('utf-8', errors='replace')
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
        df['year'] = df['record_id'].map(year_dict)
    else:
        df['year'] = np.nan

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

    df['categoria'] = df['signatura_real'].apply(clasificar_dinamico)
    return df

# ==========================================
# EJECUCIÓN SI SE HA PULSADO EL BOTÓN
# ==========================================
if st.session_state['analizado']:
    if not uploaded_topo:
        st.warning("⚠️ Por favor, sube al menos el 'Archivo Topográfico' en la página principal antes de analizar.")
    else:
        topo_bytes = uploaded_topo.getvalue()
        nunca_bytes = uploaded_nunca.getvalue() if uploaded_nunca else None
        mas2_bytes = uploaded_mas2.getvalue() if uploaded_mas2 else None
        catalogo_bytes = uploaded_catalogo.getvalue() if uploaded_catalogo else None
        
        with st.spinner("Procesando y analizando los fondos de la colección..."):
            df_completo = procesar_datos(topo_bytes, nunca_bytes, mas2_bytes, catalogo_bytes, tipo_analisis, num_caracteres)
            
        if df_completo is not None:
            st.header(f"📸 Fotografía General: {biblioteca_seleccionada}")
            
            # Ampliado a 4 columnas para incluir la población del diccionario backend
            col1, col2, col3, col4 = st.columns(4)
            
            total_docs = len(df_completo)
            pct_prestados = (df_completo['prestado'].sum() / total_docs) * 100 if total_docs > 0 else 0
            edad_media = df_completo['year'].mean()
            
            with col1:
                st.metric(label="Total Documentos", value=f"{total_docs:,}")
            with col2:
                st.metric(label="Documentos Prestados (≥ 1 vez)", value=f"{pct_prestados:.1f} %")
            with col3:
                st.metric(label="Edad Media (Año de Edición)", value=f"{int(edad_media)}" if not np.isnan(edad_media) else "N/A")
            with col4:
                st.metric(label="Población Atendida", value=f"{poblacion_atendida:,}")
                
            st.markdown("### 📊 Estado y Envejecimiento Global")
            g_col1, g_col2 = st.columns(2)
            
            with g_col1:
                status_counts = df_completo['prestamos'].map({0: 'Nunca prestado', 1: 'Prestado estándar', 2: 'Muy prestado'}).value_counts().reset_index()
                status_counts.columns = ['Estado', 'Cantidad']
                fig_pie = px.pie(status_counts, values='Cantidad', names='Estado', 
                                 title="Distribución de Uso de la Colección",
                                 color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                st.plotly_chart(fig_pie, use_container_width=True)
                
            with g_col2:
                if not df_completo['year'].dropna().empty:
                    fig_hist = px.histogram(df_completo, x='year', nbins=30,
                                            title='Antigüedad del Fondo',
                                            labels={'year': 'Año', 'count': 'Nº de Documentos'},
                                            color_discrete_sequence=['#2563EB'])
                    fig_hist.update_layout(showlegend=False)
                    st.plotly_chart(fig_hist, use_container_width=True)
                else:
                    st.info("Sube el archivo de catálogo para ver la distribución temporal.")

            st.markdown("---")
            st.header("🔍 Análisis Específico por Sección")
            
            rows = []
            for cat in df_completo['categoria'].unique():
                subset = df_completo[df_completo['categoria'] == cat]
                total = len(subset)
                if total == 0: continue
                
                prest_0 = (subset['prestamos'] == 0).sum()
                prest_1 = (subset['prestamos'] >= 1).sum()
                prest_2 = (subset['prestamos'] == 2).sum()
                
                rows.append({
                    "Sección/CDU": cat,
                    "Nº Documentos": total,
                    "Año Promedio": round(subset['year'].mean(), 1) if not subset['year'].dropna().empty else np.nan,
                    "Nunca Prestados": prest_0,
                    "Prestados (≥1)": prest_1,
                    "Muy Prestados (=2)": prest_2,
                    "% Prestados": round((prest_1 / total) * 100, 1),
                    "Índice de Uso": round(subset['prestamos'].sum() / total, 2)
                })
                
            df_tabla = pd.DataFrame(rows).sort_values(by="Nº Documentos", ascending=False)
            
            secciones_seleccionadas = st.multiselect(
                "Filtrar secciones específicas para el análisis detallado:",
                options=df_tabla['Sección/CDU'].tolist(),
                default=df_tabla['Sección/CDU'].tolist()[:10]
            )
            
            df_filtrada = df_tabla[df_tabla['Sección/CDU'].isin(secciones_seleccionadas)]
            
            fig_bar = px.bar(
                df_filtrada, x='Sección/CDU', y='Nº Documentos', color='% Prestados',
                title='Volumen de Documentos por Sección y % de Préstamo',
                color_continuous_scale=px.colors.sequential.Viridis, text_auto=True
            )
            st.plotly_chart(fig_bar, use_container_width=True)
            
            st.subheader("📋 Tabla de Indicadores para Gestión (Expurgo/Adquisición)")
            st.dataframe(
                df_filtrada.style.background_gradient(subset=['% Prestados'], cmap='YlGn')
                           .background_gradient(subset=['Nunca Prestados'], cmap='Reds')
                           .format({"Año Promedio": "{:.1f}", "% Prestados": "{:.1f}%", "Índice de Uso": "{:.2f}"}),
                use_container_width=True
            )
            
            st.markdown("### 💾 Descargar Resultados")
            col_dl1, col_dl2 = st.columns(2)
            csv = df_filtrada.to_csv(index=False).encode('utf-8')
            with col_dl1:
                st.download_button(label="📥 Descargar Análisis como CSV", data=csv, file_name='analisis_fondos.csv', mime='text/csv')
                
else:
    st.info("👋 ¡Bienvenido/a al Analizador Interactivo de Fondos!")
    st.markdown("""
    ### Instrucciones:
    1. Selecciona tu **Biblioteca** y carga los archivos `.txt` requeridos arriba en la **página principal**.
    2. Modifica el método de agrupación en la **barra lateral** (si lo deseas).
    3. Pulsa el botón azul **🚀 Analizar Fondos** ubicado en la barra lateral para procesar los datos.
    """)

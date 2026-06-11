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
    
    # 1. Lectura y Extracción del Archivo Topográfico (con Títulos)
    topo_text = topo_bytes.decode('utf-8', errors='replace')
    data = []
    for line in topo_text.split('\n'):
        line = line.strip()
        if not line or re.search(r'^(\d{2}/\d{2}/\d{4}|LISTADO|Signatura|-----)', line):
            continue
        
        # Buscar Código de Barras / Record ID
        match = re.search(r'\b(\d{7,})\b', line)
        if not match:
            continue
        record_id = int(match.group(1))
        
        # Extraer signatura real (antes del 84 XX)
        sign_match = re.search(r'(.+?)\s+84\s+[A-Z]{2}', line)
        signatura = sign_match.group(1).strip() if sign_match else line
        
        # Extraer Título (después del número identificador)
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
            # 1. MATERIAL AUDIOVISUAL
            if re.search(r'\bI\s+DVD\b', s): 
                return "I DVD (DVD Infantil)"
            if re.search(r'\bDVD\b', s): 
                return "DVD Audiovisual"

            # 2. CÓMICS / NOVELA GRÁFICA
            if re.search(r'^IC\b', s): 
                return "IC (Comic Infantil)"
            if re.search(r'^C\b', s): 
                return "C (Comic Adultos)"

            # 3. ESPECIALIDADES INFANTILES (Poesía y Teatro)
            if re.search(r'\bIP\b', s): 
                return "IP (Infantil Poesía)"
            if re.search(r'\bIT\b', s): 
                return "IT (Infantil Teatro)"

            # 4. CDU INFANTIL (Ej: "I 1", "I 3", "I 8" con espacio)
            if re.search(r'^I\s+[12356789]', s): 
                return "CDU Infantil"

            # 5. INFANTIL / JUVENIL ESTÁNDAR (Narrativa/Ficción sin espacio, ej: I1, I2, JN)
            if re.search(r'^I[0-3]', s) or re.search(r'\bJN\b', s): 
                return "Infantil / Juvenil"
            
            # 6. FICCIÓN ADULTOS (Narrativa, Poesía, Teatro)
            if re.search(r'\bN\s', s): return "Ficción / Narrativa"
            if re.search(r'\bP\s', s): return "Poesía"
            if re.search(r'\bT\s', s): return "Teatro"
            
            # 7. CDU ADULTOS (Dígito inicial)
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

    # === ¡AQUÍ ESTÁ LA CORRECCIÓN! ===
    # Aplicamos la función dinámicamente a cada fila del dataframe final
    df_final['categoria'] = df_final['signatura_real'].apply(clasificar_dinamico)
    
    # Devolvemos el dataframe procesado y el número de huérfanos
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
    
    # Bloque de KPIs comunes en la parte superior
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

    # CREACIÓN DE LAS PESTAÑAS
    tab1, tab2, tab3 = st.tabs(["📊 Distribución y Uso", "📚 Análisis por CDU / Categorías", "📋 Explorador de Colección"])

    # --- PESTAÑA 1: DISTRIBUCIÓN Y USO GENERAL ---
    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📈 Nivel de rotación física")
            status_map = {0: 'Nunca prestado', 1: 'Prestado', 2: 'Muy prestado'}
            status_counts = df_completo['prestamos'].map(status_map).value_counts().reset_index()
            status_counts.columns = ['Estado', 'Cantidad']
            fig_pie = px.pie(status_counts, values='Cantidad', names='Estado', hole=0.4,
                             color_discrete_sequence=px.colors.qualitative.Safe)
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with c2:
            st.subheader("⏳ Cronología de Ediciones")
            if not df_completo['year'].dropna().empty:
                fig_hist = px.histogram(df_completo, x='year', nbins=25, 
                                        labels={'year': 'Año de Publicación', 'count': 'Volúmenes'},
                                        color_discrete_sequence=['#1E3A8A'])
                st.plotly_chart(fig_hist, use_container_width=True)

    # --- PESTAÑA 2: NUEVO ANÁLISIS DETALLADO POR CDU ---
    with tab2:
        st.subheader("📊 Análisis de Volumen de Fondos por CDU / Categorías")
        
        # Conteo de libros por categoría
        cat_counts = df_completo['categoria'].value_counts().reset_index()
        cat_counts.columns = ['Categoría', 'Volúmenes']
        
        # Gráfico de barras horizontales interactivo
        fig_bar = px.bar(cat_counts, x='Volúmenes', y='Categoría', orientation='h',
                         text='Volúmenes', color='Volúmenes',
                         color_continuous_scale=px.colors.sequential.Blugrn)
        fig_bar.update_layout(yaxis={'categoryorder':'total ascending'}, height=500)
        st.plotly_chart(fig_bar, use_container_width=True)
        
        st.markdown("---")
        st.subheader("🔍 Desglose Métrico por Sección")
        
        # Construir una tabla analítica: Volumen, % del total y Año medio por sección
        tabla_cdu = df_completo.groupby('categoria').agg(
            Volumenes=('record_id', 'count'),
            Edad_Media=('year', lambda x: int(x.mean()) if not np.isnan(x.mean()) else np.nan),
            Prestados=('prestado', 'sum')
        ).reset_index()
        
        tabla_cdu['% de la Colección'] = (tabla_cdu['Volumenes'] / total_docs * 100).round(2)
        tabla_cdu['% Rotación Seccional'] = (tabla_cdu['Prestados'] / tabla_cdu['Volumenes'] * 100).round(2)
        
        # Reordenar y renombrar para la vista del usuario
        tabla_cdu = tabla_cdu[['categoria', 'Volumenes', '% de la Colección', 'Edad_Media', '% Rotación Seccional']]
        tabla_cdu.columns = ['Categoría / CDU', 'Nº Volúmenes', '% de la Colección', 'Año Medio Edición', '% de Uso (Prestados)']
        
        st.dataframe(tabla_cdu.sort_values(by='Nº Volúmenes', ascending=False), use_container_width=True, hide_index=True)

        # Desplegable extra para verificar la bolsa de "Otros"
        with st.expander("🔍 Inspeccionar los documentos clasificados en 'Otros'"):
            df_otros = df_completo[df_completo['categoria'] == 'Otros']
            if not df_otros.empty:
                st.dataframe(
                    df_otros[['signatura_real', 'titulo']].drop_duplicates().head(100), 
                    use_container_width=True, hide_index=True
                )
            else:
                st.success("¡Excelente! No hay ningún documento clasificado en la categoría 'Otros'.")

    # --- PESTAÑA 3: EXPLORADOR Y BUSCADOR DE TÍTULOS ---
    with tab3:
        st.subheader("📋 Inventario de Títulos Extraídos")
        st.markdown("Utiliza el buscador integrado de la tabla para localizar títulos o signaturas específicas:")
        
        # Mostrar columnas útiles incluyendo el nuevo campo "titulo"
        df_vista = df_completo[['record_id', 'signatura_real', 'categoria', 'titulo', 'year']].copy()
        df_vista.columns = ['ID Registro', 'Signatura', 'Categoría / CDU', 'Título del Documento', 'Año']
        
        st.dataframe(df_vista, use_container_width=True, hide_index=True)

else:
    st.info("👉 El panel central se activará mostrando las secciones y gráficos una vez cargues los archivos en el menú lateral.")

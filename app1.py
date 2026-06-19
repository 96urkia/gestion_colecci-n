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

    # CREACIÓN DE LAS PESTAÑAS (Aquí cambiamos el nombre de la 3)
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Distribución y Uso", 
        "📚 Análisis por Categorías", 
        "🔎 Análisis exhaustivo por CDU", 
        "📋 Explorador de Colección"
    ])

    # --- PESTAÑA 1: DISTRIBUCIÓN Y USO GENERAL ---
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

    # --- PESTAÑA 2: ANÁLISIS DE VOLUMEN DE FONDOS ---
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

   # --- PESTAÑA 3: ANÁLISIS EXHAUSTIVO POR CDU (JERARQUÍA FILTRADA Y ESTRICTA) ---
    with tab3:
        st.subheader("🔎 Análisis exhaustivo por CDU")
        st.markdown("Explora la estructura de la colección. El árbol se despliega nivel a nivel.")

        def convertir_a_csv(df):
            cols_export = ['record_id', 'signatura_real', 'titulo', 'year', 'prestamos', 'prestado']
            df_export = df[cols_export].copy()
            df_export.columns = ['Nº Registro', 'CDU / Signatura', 'Título', 'Año', 'Nº Préstamos', '¿Prestado?']
            return df_export.to_csv(index=False, sep=';', encoding='utf-8-sig')

        def generar_seccion_resumen(df_sub, nombre_nivel, ruta_completa):
            vols = len(df_sub)
            if vols == 0: return
            
            pct_coll = (vols / total_docs * 100)
            edad_m = df_sub['year'].mean()
            pct_prest = (df_sub['prestado'].sum() / vols * 100)
            
            df_met = pd.DataFrame({
                "Nº Volúmenes": [f"{vols:,}"],
                "% Colección": [f"{pct_coll:.1f}%"],
                "Edad Media": [f"{int(edad_m)}" if not np.isnan(edad_m) else "N/A"],
                "% Préstamos": [f"{pct_prest:.1f}%"]
            })
            st.table(df_met)
            
            # Hash único basado en el contenido del dataframe para evitar duplicidad de botones
            unique_hash = hash(tuple(df_sub.index.tolist()))
            st.download_button(
                label=f"📥 Descargar lista: {nombre_nivel}",
                data=convertir_a_csv(df_sub),
                file_name=f"export_{str(nombre_nivel).replace(' ', '_')[:20]}.csv",
                mime="text/csv",
                key=f"dl_{ruta_completa}_{unique_hash}"
            )

        def render_niveles(df_actual, prefijo_actual, ruta_path):
            def obtener_siguientes_nodos(df, prefijo):
                nodos_hijos = set()
                # Extraemos el prefijo de la signatura para identificar el siguiente nivel
                for sig in df['signatura_real'].unique():
                    sig = str(sig)
                    if sig.startswith(prefijo):
                        # Limpiamos prefijo y delimitadores comunes
                        resto = sig[len(prefijo):].lstrip('. ()')
                        
                        # Filtro de autor (ignora 3 letras)
                        if re.match(r'^[A-Za-z]{3}$', resto): continue
                        
                        # Captura el primer bloque (número o paréntesis)
                        match = re.match(r'^([0-9]+|\([0-9]+\))', resto)
                        if match:
                            bloque = match.group(1)
                            if re.match(r'^[A-Za-z]{3}$', bloque): continue
                            nodos_hijos.add(bloque)
                return sorted(list(nodos_hijos))

            nodos = obtener_siguientes_nodos(df_actual, prefijo_actual)
            
            for nodo in nodos:
                # Patrón para asegurar que el nodo es un segmento independiente
                # Buscamos el nodo como bloque aislado
                patron = f"{re.escape(prefijo_actual.strip())}\\.?\\s?\\(?{re.escape(nodo.replace('(', '').replace(')', ''))}".strip()
                df_hijo = df_actual[df_actual['signatura_real'].str.contains(patron, regex=True, na=False)]
                
                if len(df_hijo) > 0:
                    nueva_ruta = f"{ruta_path}_{nodo.replace('(', '').replace(')', '')}"
                    
                    with st.expander(f"📁 {nodo} ({len(df_hijo)} volúmenes)"):
                        generar_seccion_resumen(df_hijo, nodo, nueva_ruta)
                        
                        # Comprobamos si tiene subdivisiones más profundas
                        hijos_del_hijo = obtener_siguientes_nodos(df_hijo, f"{prefijo_actual} {nodo}".strip())
                        
                        if hijos_del_hijo:
                            render_niveles(df_hijo, f"{prefijo_actual} {nodo}".strip(), nueva_ruta)
                        else:
                            st.dataframe(df_hijo[['signatura_real', 'titulo', 'year']], use_container_width=True, hide_index=True)

        # Inicio del árbol de categorías
        for cat in sorted(df_completo['categoria'].unique()):
            df_cat = df_completo[df_completo['categoria'] == cat]
            if len(df_cat) > 0:
                with st.expander(f"📚 {cat} ({len(df_cat)} volúmenes)"):
                    generar_seccion_resumen(df_cat, cat, cat)
                    render_niveles(df_cat, "", cat)

                
    # --- PESTAÑA 4: EXPLORADOR Y BUSCADOR DE TÍTULOS ---
    with tab4:
        st.subheader("📋 Inventario de Títulos Extraídos")
        st.markdown("Utiliza el buscador integrado de la tabla para localizar títulos o signaturas específicas:")
        
        df_vista = df_completo[['record_id', 'signatura_real', 'categoria', 'titulo', 'year']].copy()
        df_vista.columns = ['ID Registro', 'Signatura', 'Categoría / CDU', 'Título del Documento', 'Año']
        st.dataframe(df_vista, use_container_width=True, hide_index=True)

else:
    st.info("👉 El panel central se activará mostrando las secciones y gráficos una vez cargues los archivos en el menú lateral")

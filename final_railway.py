import sys
import xml.etree.ElementTree as ET
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget,
                             QPushButton, QFileDialog, QLabel, QMessageBox,
                             QComboBox, QHBoxLayout, QGroupBox)
from PyQt5.QtCore import Qt
import networkx as nx
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas


class GraphVisualizer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Анализ транспортной сети")
        self.setGeometry(100, 100, 1200, 800)

        self.graph = None
        self.current_file = ""
        self.G_transformed = None
        self.pos = None
        self.edge_labels = {}
        self.min_cut_nodes = []
        self.min_cut_edges = []
        self.source_node = ""
        self.sink_node = ""

        self.initUI()

    def initUI(self):
        # Главный виджет и компоновка
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)

        # Группа управления
        control_group = QGroupBox("Управление")
        control_layout = QHBoxLayout()
        control_group.setLayout(control_layout)

        # Кнопки загрузки и отрисовки
        self.load_button = QPushButton("Загрузить GraphML")
        self.load_button.clicked.connect(self.load_graphml)
        control_layout.addWidget(self.load_button)

        self.draw_button = QPushButton("Отрисовать граф")
        self.draw_button.clicked.connect(self.draw_graph)
        self.draw_button.setEnabled(False)
        control_layout.addWidget(self.draw_button)

        # Выбор источника и стока
        control_layout.addWidget(QLabel("Источник:"))
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(100)
        control_layout.addWidget(self.source_combo)

        control_layout.addWidget(QLabel("Сток:"))
        self.sink_combo = QComboBox()
        self.sink_combo.setMinimumWidth(100)
        control_layout.addWidget(self.sink_combo)

        # Кнопка расчета разреза
        self.calc_button = QPushButton("Найти минимальный разрез")
        self.calc_button.clicked.connect(self.calculate_min_cut)
        self.calc_button.setEnabled(False)
        control_layout.addWidget(self.calc_button)

        main_layout.addWidget(control_group)

        # Информация о файле
        self.file_label = QLabel("Файл не загружен")
        self.file_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.file_label)

        # Графическая область
        self.figure = plt.figure(figsize=(12, 6))
        self.canvas = FigureCanvas(self.figure)
        main_layout.addWidget(self.canvas)

    def parse_custom_graphml(self, graphml_str):
        """Парсинг GraphML вручную"""
        root = ET.fromstring(graphml_str)
        
        # Определяем тип графа
        graph_elem = root.find('.//{http://graphml.graphdrawing.org/xmlns}graph')
        edgedefault = graph_elem.get('edgedefault', 'undirected')
        G = nx.DiGraph() if edgedefault == 'directed' else nx.Graph()
        
        # Словари для атрибутов
        node_attrs = {}
        edge_attrs = {}
        
        # Парсинг узлов
        for node in root.findall('.//{http://graphml.graphdrawing.org/xmlns}node'):
            node_id = node.get('id')
            G.add_node(node_id)
            node_attrs[node_id] = {}
            
        # Парсинг рёбер
        for edge in root.findall('.//{http://graphml.graphdrawing.org/xmlns}edge'):
            source = edge.get('source')
            target = edge.get('target')
            edge_id = edge.get('id')
            
            # Атрибуты ребра
            attrs = {}
            for data in edge.findall('{http://graphml.graphdrawing.org/xmlns}data'):
                key = data.get('key')
                value = data.text.strip('"') if data.text else ""
                attrs[key] = value
            
            G.add_edge(source, target, id=edge_id, **attrs)
            edge_attrs[(source, target)] = attrs
        
        return G, node_attrs, edge_attrs

    def build_transformed_graph(self, G0, edge_attrs):
        """Построение преобразованного графа для расчета разреза"""
        # Создаем направленный граф
        G_dir = nx.DiGraph()
        G_dir.add_nodes_from(G0.nodes(data=True))
        
        # Обработка рёбер
        for u, v, data in G0.edges(data=True):
            # Извлекаем пропускную способность (поддержка q и Q)
            q_value = data.get('q', data.get('Q', '60'))
            try:
                forward_cap = float(q_value)
            except ValueError:
                forward_cap = 0.0
            
            # Обратная пропускная способность равна прямой
            backward_cap = forward_cap
            
            # Добавляем ребра
            G_dir.add_edge(u, v, capacity=forward_cap)
            G_dir.add_edge(v, u, capacity=backward_cap)
        
        # Преобразованный граф
        G_transformed = nx.DiGraph()
        BIG_NUMBER = 10**18
        
        # Преобразование узлов
        for node in G_dir.nodes():
            in_node = f"{node}_in"
            out_node = f"{node}_out"
            cap = BIG_NUMBER
            
            # Внутреннее ребро узла
            G_transformed.add_edge(in_node, out_node, 
                                capacity=cap,
                                type='node', 
                                original_node=node)
        
        # Добавляем исходные ребра
        for u, v, data in G_dir.edges(data=True):
            u_out = f"{u}_out"
            v_in = f"{v}_in"
            
            G_transformed.add_edge(u_out, v_in, 
                                capacity=data['capacity'],
                                type='edge',
                                original_edge=(u, v))
        
        # Создаем подписи для рёбер (поддержка q и Q)
        edge_labels = {}
        for u, v in G0.edges():
            attrs = edge_attrs.get((u, v), {})
            q_val = attrs.get('q', attrs.get('Q', '?'))
            edge_labels[(u, v)] = q_val
        
        return G_transformed, edge_labels

    def load_graphml(self):
        """Загрузка GraphML файла"""
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Открыть GraphML файл", "", "GraphML файлы (*.graphml *.xml)")

        if file_name:
            try:
                # Чтение файла
                with open(file_name, 'r', encoding='utf-8') as file:
                    graphml_data = file.read()
                
                # Парсинг вручную
                G0, node_attrs, edge_attrs = self.parse_custom_graphml(graphml_data)
                
                # Построение преобразованного графа
                self.G_transformed, self.edge_labels = self.build_transformed_graph(G0, edge_attrs)
                self.graph = G0
                self.current_file = file_name
                self.file_label.setText(f"Загружен: {file_name}")
                self.draw_button.setEnabled(True)
                self.calc_button.setEnabled(True)
                
                # Заполнение комбобоксов узлами
                self.source_combo.clear()
                self.sink_combo.clear()
                nodes = list(G0.nodes())
                self.source_combo.addItems(nodes)
                self.sink_combo.addItems(nodes)
                
                # Сохраняем позиции для визуализации
                self.pos = nx.spring_layout(G0)
                
                # Сброс предыдущего разреза
                self.min_cut_nodes = []
                self.min_cut_edges = []

            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки файла:\n{str(e)}")
                self.graph = None
                self.current_file = ""
                self.file_label.setText("Файл не загружен")
                self.draw_button.setEnabled(False)
                self.calc_button.setEnabled(False)

    def draw_graph(self, highlight_cut=False):
        """Отрисовка графа с возможностью выделения разреза"""
        if self.graph is None:
            return

        try:
            self.figure.clear()
            ax = self.figure.add_subplot(111)
            
            # Цвета узлов
            node_colors = []
            for node in self.graph.nodes():
                if highlight_cut and node in self.min_cut_nodes:
                    node_colors.append('red')
                else:
                    node_colors.append('skyblue')
            
            # Цвета и толщина ребер
            edge_colors = []
            edge_widths = []
            for edge in self.graph.edges():
                if highlight_cut and edge in self.min_cut_edges:
                    edge_colors.append('red')
                    edge_widths.append(3)
                else:
                    edge_colors.append('gray')
                    edge_widths.append(1)
            
            # Отрисовка графа
            nx.draw(self.graph, self.pos, ax=ax, with_labels=True, 
                    node_color=node_colors, node_size=700,
                    edge_color=edge_colors, width=edge_widths, 
                    linewidths=1, font_size=10, font_weight='bold')
            
            # Подписи пропускных способностей
            nx.draw_networkx_edge_labels(
                self.graph, self.pos, ax=ax,
                edge_labels=self.edge_labels,
                font_size=9
            )
            
            # Заголовок
            title = f"Граф: {self.current_file}"
            if highlight_cut and self.source_node and self.sink_node:
                title += f"\nМинимальный разрез между {self.source_node} и {self.sink_node}"
            ax.set_title(title)
            
            self.canvas.draw()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка отрисовки графа:\n{str(e)}")

    def calculate_min_cut(self):
        """Расчет минимального разреза"""
        if self.graph is None or self.G_transformed is None:
            return
            
        try:
            # Получаем выбранные узлы
            self.source_node = self.source_combo.currentText()
            self.sink_node = self.sink_combo.currentText()
            
            if not self.source_node or not self.sink_node or self.source_node == self.sink_node:
                QMessageBox.warning(self, "Ошибка", "Выберите различные источник и сток")
                return
                
            source = f"{self.source_node}_in"
            sink = f"{self.sink_node}_out"
            
            # Расчет минимального разреза
            cut_value, partition = nx.minimum_cut(self.G_transformed, source, sink, capacity='capacity')
            reachable, non_reachable = partition
            
            # Находим ребра разреза
            cut_edges = []
            for u in reachable:
                for v in self.G_transformed[u]:
                    if v in non_reachable:
                        cut_edges.append((u, v))
            
            # Определяем элементы разреза в исходном графе
            self.min_cut_nodes = []
            self.min_cut_edges = []
            
            for u, v in cut_edges:
                edge_data = self.G_transformed[u][v]
                if edge_data['type'] == 'node':
                    self.min_cut_nodes.append(edge_data['original_node'])
                elif edge_data['type'] == 'edge':
                    self.min_cut_edges.append(edge_data['original_edge'])
            
            # Отрисовка с выделением разреза
            self.draw_graph(highlight_cut=True)
            
            # Информационное сообщение
            QMessageBox.information(
                self, "Результат", 
                f"Минимальный разрез между {self.source_node} и {self.sink_node}\n"
                f"Пропускная способность: {cut_value}\n"
                f"Узлы в разрезе: {', '.join(self.min_cut_nodes)}\n"
                f"Рёбра в разрезе: {', '.join(map(str, self.min_cut_edges))}"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка расчета", f"Ошибка при расчете минимального разреза:\n{str(e)}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GraphVisualizer()
    window.show()
    sys.exit(app.exec_())
import asyncio
import logging
from datetime import datetime
from PyQt5.QtCore import QPointF, pyqtSignal, Qt
from PyQt5.QtGui import QIcon, QColor
from PyQt5.QtWidgets import QMainWindow, QStatusBar, QMessageBox
import pyqtgraph as pg
from pyqtgraph import (AxisItem, FillBetweenItem, GraphicsLayoutWidget,
                       InfiniteLine, LinearRegionItem, PlotDataItem, TextItem,
                       ViewBox, PlotItem)
from ..bridge.mt4_bridge import mt4_bridge
from ..services.order_db_manager import order_db_manager
from ..tools import tool_market, tool_patterns, tool_utility
import resources.resources_rc
logger = logging.getLogger(__name__)
class DateAxis(AxisItem):
    def __init__(self, candles, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.candles = candles
    def tickStrings(self, values, scale, spacing):
        strings = []
        if not self.candles:
            return ['' for _ in values]
        for v in values:
            index = int(v)
            if 0 <= index < len(self.candles):
                try:
                    dt_obj = datetime.strptime(self.candles[index]['time'], '%Y.%m.%d %H:%M')
                    strings.append(dt_obj.strftime('%d %b %H:%M'))
                except (ValueError, KeyError):
                    strings.append('')
            else:
                strings.append('')
        return strings
class CandlestickItem(pg.GraphicsObject):
    def __init__(self, data):
        pg.GraphicsObject.__init__(self)
        self.data = data
        self.generatePicture()
    def generatePicture(self):
        self.picture = pg.QtGui.QPicture()
        p = pg.QtGui.QPainter(self.picture)
        w = 0.4
        for (t, open_price, high, low, close_price) in self.data:
            pen_color = '#00FF00' if open_price < close_price else '#FF0000'
            brush_color = QColor(0, 255, 0, 150) if open_price < close_price else QColor(255, 0, 0, 150)
            p.setPen(pg.mkPen(pen_color))
            p.setBrush(pg.mkBrush(brush_color))
            p.drawLine(QPointF(t, low), QPointF(t, high))
            p.drawRect(pg.QtCore.QRectF(t - w, open_price, w * 2, close_price - open_price))
        p.end()
    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)
    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())
class ChartDataModel:
    def __init__(self):
        self.ticket: int = 0
        self.symbol: str = ""
        self.timeframe: int = 0
        self.candles: list = []
        self.patterns: dict = {}
        self.indicators: dict = {}
        self.order_info: dict = {}
class ChartView(GraphicsLayoutWidget):
    def __init__(self):
        super().__init__()
        self.setBackground('#1A1D2A')
        self.ci.layout.setColumnStretchFactor(1, 20)
        self.main_plot = None
        self.rsi_plot = None
        self.items_to_clear = []
        self.proxy = pg.SignalProxy(self.scene().sigMouseMoved, rateLimit=60, slot=self.mouse_moved)
    def _setup_plots(self):
        self.main_plot.showAxis('right')
        self.main_plot.hideAxis('left')
        self.main_plot.hideAxis('bottom')
        self.rsi_plot.showAxis('right')
        self.rsi_plot.hideAxis('left')
        self.rsi_plot.showAxis('bottom')
        self.main_plot.showGrid(x=True, y=True, alpha=0.3)
        self.rsi_plot.showGrid(x=True, y=True, alpha=0.3)
        self.rsi_plot.setXLink(self.main_plot)
        self.rsi_plot.setMaximumHeight(150)
        self.main_plot.getAxis('right').setLabel('Price', color='#FFFFFF')
        self.rsi_plot.getAxis('right').setLabel('RSI', color='#FFFFFF')
        self.rsi_plot.setYRange(0, 100)
        self.main_plot.getAxis('right').setWidth(60)
        self.rsi_plot.getAxis('right').setWidth(60)
        self.main_plot.vb.setMouseMode(ViewBox.PanMode)
        self.main_plot.vb.disableAutoRange()
        self.rsi_plot.vb.disableAutoRange()
        self.rsi_plot.addItem(InfiniteLine(pos=70, angle=0, movable=False, pen=pg.mkPen('w', style=pg.QtCore.Qt.DashLine)))
        self.rsi_plot.addItem(InfiniteLine(pos=30, angle=0, movable=False, pen=pg.mkPen('w', style=pg.QtCore.Qt.DashLine)))
        self.v_line = InfiniteLine(angle=90, movable=False, pen=pg.mkPen('w', style=pg.QtCore.Qt.DotLine))
        self.h_line_main = InfiniteLine(angle=0, movable=False, pen=pg.mkPen('w', style=pg.QtCore.Qt.DotLine))
        self.h_line_rsi = InfiniteLine(angle=0, movable=False, pen=pg.mkPen('w', style=pg.QtCore.Qt.DotLine))
        self.info_text = TextItem("")
        self.info_text.setZValue(100)
        self.main_plot.addItem(self.info_text, ignoreBounds=True)
        self.main_plot.addItem(self.v_line, ignoreBounds=True)
        self.main_plot.addItem(self.h_line_main, ignoreBounds=True)
        self.rsi_plot.addItem(self.h_line_rsi, ignoreBounds=True)
    def mouse_moved(self, evt):
        if self.main_plot is None or not self.main_plot.scene():
            return
        pos = evt[0]
        if self.main_plot.sceneBoundingRect().contains(pos):
            mouse_point_main = self.main_plot.vb.mapSceneToView(pos)
            index = int(round(mouse_point_main.x()))
            self.v_line.setPos(mouse_point_main.x())
            self.h_line_main.setPos(mouse_point_main.y())
            mouse_point_rsi = self.rsi_plot.vb.mapSceneToView(pos)
            self.h_line_rsi.setPos(mouse_point_rsi.y())
            if hasattr(self, 'candles') and 0 <= index < len(self.candles):
                candle = self.candles[index]
                dt_obj = datetime.strptime(candle['time'], '%Y.%m.%d %H:%M')
                time_str_info = dt_obj.strftime('%Y-%m-%d %H:%M')
                price_at_cursor = mouse_point_main.y()
                rsi_value = 'N/A'
                if hasattr(self, 'rsi_values') and hasattr(self, 'rsi_start_index') and 0 <= index - self.rsi_start_index < len(self.rsi_values):
                    rsi_value = self.rsi_values[index - self.rsi_start_index]
                ema_value = 'N/A'
                if hasattr(self, 'ema_values') and hasattr(self, 'ema_start_index') and 0 <= index - self.ema_start_index < len(self.ema_values):
                    ema_value = self.ema_values[index - self.ema_start_index]
                bb_upper_value, bb_middle_value, bb_lower_value = 'N/A', 'N/A', 'N/A'
                if hasattr(self, 'bbands_upper') and hasattr(self, 'bbands_start_index') and 0 <= index - self.bbands_start_index < len(self.bbands_upper):
                    bb_upper_value = self.bbands_upper[index - self.bbands_start_index]
                    bb_middle_value = self.bbands_middle[index - self.bbands_start_index]
                    bb_lower_value = self.bbands_lower[index - self.bbands_start_index]
                price_str = f'{price_at_cursor:.5f}'
                rsi_str = f'{rsi_value:.2f}' if isinstance(rsi_value, float) else rsi_value
                ema_str = f'{ema_value:.5f}' if isinstance(ema_value, float) else ema_value
                bb_upper_str = f'{bb_upper_value:.5f}' if isinstance(bb_upper_value, float) else bb_upper_value
                bb_middle_str = f'{bb_middle_value:.5f}' if isinstance(bb_middle_value, float) else bb_middle_value
                bb_lower_str = f'{bb_lower_value:.5f}' if isinstance(bb_lower_value, float) else bb_lower_value
                info = (f"<div style='background-color: rgba(30, 30, 30, 0.8); color: white; padding: 5px; border-radius: 3px; font-size: 10pt;'>"
                        f"<b>Time:</b> {time_str_info}<br>"
                        f"<b>Open:</b> {candle['open']}<br>"
                        f"<b>High:</b> {candle['high']}<br>"
                        f"<b>Low:</b> {candle['low']}<br>"
                        f"<b>Close:</b> {candle['close']}<br>"
                        f"<b>Price:</b> {price_str}<br>"
                        f"<b>RSI(14):</b> {rsi_str}<br>"
                        f"<b>EMA(89):</b> {ema_str}<br>"
                        f"<b>BB(20,2):</b> {bb_upper_str} | {bb_middle_str} | {bb_lower_str}</div>")
                self.info_text.setHtml(info)
                view_range = self.main_plot.vb.viewRange()
                x_range, y_range = view_range[0], view_range[1]
                if not x_range or not y_range or x_range[0] == x_range[1] or y_range[0] == y_range[1]:
                    self.info_text.setAnchor((0.5, 0.5))
                    self.info_text.setPos(mouse_point_main.x(), mouse_point_main.y())
                    return
                x_mid = (x_range[0] + x_range[1]) / 2
                y_mid = (y_range[0] + y_range[1]) / 2
                cursor_x = mouse_point_main.x()
                cursor_y = mouse_point_main.y()
                if cursor_x < x_mid and cursor_y <= y_mid:
                    self.info_text.setAnchor((0, 1))
                elif cursor_x >= x_mid and cursor_y <= y_mid:
                    self.info_text.setAnchor((1, 1))
                elif cursor_x < x_mid and cursor_y > y_mid:
                    self.info_text.setAnchor((0, 0))
                else:
                    self.info_text.setAnchor((1, 0))
                self.info_text.setPos(cursor_x, cursor_y)
            else:
                self.info_text.setHtml("")
    def clear_all(self):
        if not self.main_plot:
            return
        for item in self.items_to_clear:
            try:
                if item and item.scene(): item.scene().removeItem(item)
            except Exception: pass
        self.items_to_clear.clear()
        if self.main_plot.legend: self.main_plot.legend.clear()
    def update_view(self, model: ChartDataModel):
        self.clear_all()
        if not model.candles: return
        self.candles = model.candles
        if self.main_plot is None:
            date_axis_main = DateAxis(self.candles, orientation='bottom')
            right_axis_main = AxisItem(orientation='right')
            date_axis_rsi = DateAxis(self.candles, orientation='bottom')
            right_axis_rsi = AxisItem(orientation='right')
            self.main_plot = PlotItem(axisItems={'bottom': date_axis_main, 'right': right_axis_main})
            self.rsi_plot = PlotItem(axisItems={'bottom': date_axis_rsi, 'right': right_axis_rsi})
            self.addItem(self.main_plot, row=0, col=1)
            self.addItem(self.rsi_plot, row=1, col=1)
            self._setup_plots()
        else:
            self.main_plot.getAxis('bottom').candles = self.candles
            self.rsi_plot.getAxis('bottom').candles = self.candles
        self._draw_candlesticks(model.candles)
        self._draw_indicators(model)
        self._draw_patterns(model.patterns, model.candles)
        self._draw_trade_levels(model.order_info, model.timeframe)
    def _draw_candlesticks(self, candles: list):
        candle_data = [(i, c['open'], c['high'], c['low'], c['close']) for i, c in enumerate(candles)]
        candlestick_item = CandlestickItem(candle_data)
        self.main_plot.addItem(candlestick_item)
        self.items_to_clear.append(candlestick_item)
        visible_candles = candles[-100:] if len(candles) > 100 else candles
        if not visible_candles: return
        min_low = min(c['low'] for c in visible_candles)
        max_high = max(c['high'] for c in visible_candles)
        y_margin = (max_high - min_low) * 0.1
        self.main_plot.setYRange(min_low - y_margin, max_high + y_margin)
        self.main_plot.setXRange(len(candles) - 100, len(candles))
    def _draw_indicators(self, model: ChartDataModel):
        if 'ema' in model.indicators and model.indicators['ema']:
            self.ema_values = model.indicators['ema'].get('data', {}).get('ema_values', [])
            if self.ema_values:
                self.ema_start_index = len(model.candles) - len(self.ema_values)
                ema_item = PlotDataItem(x=list(range(self.ema_start_index, self.ema_start_index + len(self.ema_values))), y=self.ema_values, pen=pg.mkPen('#FFD700', width=2), name='EMA(89)')
                self.main_plot.addItem(ema_item)
                self.items_to_clear.append(ema_item)
        if 'rsi' in model.indicators and model.indicators['rsi']:
            self.rsi_values = model.indicators['rsi'].get('data', {}).get('rsi_values', [])
            if self.rsi_values:
                self.rsi_start_index = len(model.candles) - len(self.rsi_values)
                rsi_item = PlotDataItem(x=list(range(self.rsi_start_index, self.rsi_start_index + len(self.rsi_values))), y=self.rsi_values, pen=pg.mkPen('#00FFFF', width=2))
                self.rsi_plot.addItem(rsi_item)
                self.items_to_clear.append(rsi_item)
        if 'bbands' in model.indicators and model.indicators['bbands']:
            bbands_data = model.indicators['bbands'].get('data', {})
            self.bbands_upper = bbands_data.get('upper_band', [])
            self.bbands_middle = bbands_data.get('middle_band', [])
            self.bbands_lower = bbands_data.get('lower_band', [])
            if self.bbands_upper:
                self.bbands_start_index = len(model.candles) - len(self.bbands_middle)
                x_coords = list(range(self.bbands_start_index, self.bbands_start_index + len(self.bbands_middle)))
                pen_upper_lower = pg.mkPen(color=(0, 150, 255, 150), style=pg.QtCore.Qt.DotLine)
                pen_middle = pg.mkPen(color=(255, 255, 0, 150), style=pg.QtCore.Qt.DashLine)
                upper_item = PlotDataItem(x=x_coords, y=self.bbands_upper, pen=pen_upper_lower)
                middle_item = PlotDataItem(x=x_coords, y=self.bbands_middle, pen=pen_middle, name='BBands(20,2)')
                lower_item = PlotDataItem(x=x_coords, y=self.bbands_lower, pen=pen_upper_lower)
                fill = FillBetweenItem(curve1=upper_item, curve2=lower_item, brush=pg.mkBrush(0, 150, 255, 40))
                self.main_plot.addItem(upper_item)
                self.main_plot.addItem(middle_item)
                self.main_plot.addItem(lower_item)
                self.main_plot.addItem(fill)
                self.items_to_clear.extend([upper_item, middle_item, lower_item, fill])
        if 'vegas' in model.indicators and model.indicators['vegas']:
            vegas_data = model.indicators['vegas'].get('data', {})
            ema144_values = vegas_data.get('ema_144', [])
            ema169_values = vegas_data.get('ema_169', [])
            if ema144_values and ema169_values:
                len144, len169 = len(ema144_values), len(ema169_values)
                if len144 > len169:
                    diff = len144 - len169
                    ema144_values = ema144_values[diff:]
                elif len169 > len144:
                    diff = len169 - len144
                    ema169_values = ema169_values[diff:]
                start_index = len(model.candles) - len(ema144_values)
                x_coords = list(range(start_index, start_index + len(ema144_values)))
                pen1 = pg.mkPen(color='#8A2BE2', width=1.5)
                pen2 = pg.mkPen(color='#9370DB', width=1.5)
                item1 = PlotDataItem(x=x_coords, y=ema144_values, pen=pen1, name='EMA(144)')
                item2 = PlotDataItem(x=x_coords, y=ema169_values, pen=pen2, name='EMA(169)')
                fill = FillBetweenItem(curve1=item1, curve2=item2, brush=pg.mkBrush(138, 43, 226, 30))
                self.main_plot.addItem(item1)
                self.main_plot.addItem(item2)
                self.main_plot.addItem(fill)
                self.items_to_clear.extend([item1, item2, fill])
    def _find_candle_index(self, candles: list, timestamp_str: str):
        for i, candle in enumerate(candles):
            if candle['time'] == timestamp_str: return i
        return -1
    def _draw_patterns(self, patterns: dict, candles: list):
        if not patterns: return
        price_action_data = patterns.get('price_action', {})
        pa_patterns = price_action_data.get('patterns', [])
        pa_labels = {
            "Bullish Pin Bar": "PIN", "Bearish Pin Bar": "PIN",
            "Bullish Engulfing": "ENG", "Bearish Engulfing": "ENG",
            "Inside Bar": "INS"
        }
        if pa_patterns:
            for pa_result in pa_patterns:
                candle = pa_result.get('candle') or pa_result.get('engulfing_candle') or pa_result.get('inside_candle')
                if not candle: continue
                idx = self._find_candle_index(candles, candle['time'])
                if idx == -1: continue
                pa_type = pa_result.get('type', '')
                is_bullish = "Bullish" in pa_type
                label_text = pa_labels.get(pa_type, "?")
                if label_text == 'INS':
                    color = '#FFD700'
                else:
                    color = '#ADFF2F' if is_bullish else '#FF4500'
                y_range_tuple = self.main_plot.vb.viewRange()
                if y_range_tuple and y_range_tuple[1]:
                    y_range = y_range_tuple[1]
                    y_offset = (y_range[1] - y_range[0]) * 0.03 if y_range[1] > y_range[0] else 0.0
                else:
                    y_offset = (candle['high'] - candle['low']) * 0.1
                pos_y = candle['low'] - y_offset if is_bullish or label_text == 'INS' else candle['high'] + y_offset
                html_text = f"<div style='background-color:rgba(10,10,10,0.6); color: {color}; font-size: 8pt; padding: 1px 3px; border-radius: 2px;'>{label_text}</div>"
                text = TextItem(html=html_text, anchor=(0.5, 0.5))
                text.setPos(idx, pos_y)
                self.main_plot.addItem(text)
                self.items_to_clear.append(text)
        structures_data = patterns.get('structures', {})
        if not isinstance(structures_data, dict): return
        harmonics = structures_data.get('harmonics', [])
        for harmonic in harmonics:
            points = harmonic.get('points', {})
            point_labels = ['X', 'A', 'B', 'C', 'D']
            if not all(p in points for p in point_labels): continue
            coords = []
            for label in point_labels:
                p_data = points[label]
                idx = self._find_candle_index(candles, p_data['time'])
                if idx == -1:
                    coords = []
                    break
                price = p_data['price']
                coords.append({'x': idx, 'y': price})
                anchor = (0.5, -0.7) if p_data['type'] == 'high' else (0.5, 1.7)
                text = TextItem(label, anchor=anchor, color='cyan')
                text.setPos(idx, price)
                self.main_plot.addItem(text)
                self.items_to_clear.append(text)
            if len(coords) == 5:
                    x, y = [c['x'] for c in coords], [c['y'] for c in coords]
                    pen = pg.mkPen('#0096FF', style=pg.QtCore.Qt.DashLine, width=1.5)
                    harmonic_item = PlotDataItem(x=x, y=y, pen=pen, symbol='o', symbolBrush='#0096FF', symbolPen='c', name=harmonic.get('type', 'Harmonic'))
                    self.main_plot.addItem(harmonic_item)
                    self.items_to_clear.append(harmonic_item)
        zones_data = structures_data.get('demand_supply_zones', {})
        if isinstance(zones_data, dict) and zones_data.get('found'):
            for zone in zones_data.get('zones', [])[:5]:
                is_demand = "Demand" in zone['type']
                color = QColor(0, 255, 0, 40) if is_demand else QColor(255, 0, 0, 40)
                pen = pg.mkPen(QColor(0, 255, 0, 80) if is_demand else QColor(255, 0, 0, 80), width=1, style=pg.QtCore.Qt.DotLine)
                region = LinearRegionItem(values=[zone['bottom'], zone['top']], orientation='horizontal', brush=color, pen=pen, movable=False)
                label_text = "Demand Zone" if is_demand else "Supply Zone"
                label_color = QColor(173, 255, 47, 220) if is_demand else QColor(255, 69, 0, 220)
                label_y = (zone['top'] + zone['bottom']) / 2
                x_range = self.main_plot.vb.viewRange()[0]
                label_x = x_range[1] if x_range and len(x_range) > 1 else 0
                label = TextItem(label_text, color=label_color, anchor=(0, 0.5))
                label.setPos(label_x, label_y)
                self.main_plot.addItem(region)
                self.main_plot.addItem(label)
                self.items_to_clear.extend([region, label])
        fibo_data = structures_data.get('fibonacci', {})
        if isinstance(fibo_data, dict) and fibo_data.get('found'):
            levels = fibo_data.get('levels', {})
            start_point = fibo_data.get('start_point')
            end_point = fibo_data.get('end_point')
            if start_point and end_point:
                start_idx = self._find_candle_index(candles, start_point['time'])
                end_idx = self._find_candle_index(candles, end_point['time'])
                start_price = start_point.get('swing_price', start_point['low'] if fibo_data.get('is_uptrend') else start_point['high'])
                end_price = end_point.get('swing_price', end_point['high'] if fibo_data.get('is_uptrend') else end_point['low'])
                if start_idx != -1 and end_idx != -1:
                    pen = pg.mkPen(color=(255, 255, 0, 100), style=pg.QtCore.Qt.DashDotLine, width=2)
                    fibo_ruler = PlotDataItem(x=[start_idx, end_idx], y=[start_price, end_price], pen=pen)
                    self.main_plot.addItem(fibo_ruler)
                    self.items_to_clear.append(fibo_ruler)
            pen_color = pg.mkPen(color=(255, 215, 0, 150), style=pg.QtCore.Qt.DotLine)
            for level_str, price in levels.items():
                label_text = f"Fibo {level_str}"
                label_opts = {'position': 0.85, 'color': (255, 215, 0, 200), 'movable': True, 'fill': (30, 30, 30, 180)}
                fibo_line = InfiniteLine(pos=price, angle=0, pen=pen_color, label=label_text, labelOpts=label_opts)
                self.main_plot.addItem(fibo_line)
                self.items_to_clear.append(fibo_line)
        sr_data = structures_data.get('sr_levels', {})
        if isinstance(sr_data, dict) and sr_data.get('found'):
            resistance_pen = pg.mkPen(color=(255, 80, 80, 200), width=1.5)
            support_pen = pg.mkPen(color=(80, 255, 80, 200), width=1.5)
            for r_price in sr_data.get('resistances', []):
                line = InfiniteLine(pos=r_price, angle=0, pen=resistance_pen,
                                    label='Resistance', labelOpts={'position':0.9, 'color': (255, 80, 80)})
                self.main_plot.addItem(line)
                self.items_to_clear.append(line)
            for s_price in sr_data.get('supports', []):
                line = InfiniteLine(pos=s_price, angle=0, pen=support_pen,
                                    label='Support', labelOpts={'position':0.9, 'color': (80, 255, 80)})
                self.main_plot.addItem(line)
                self.items_to_clear.append(line)
    def _draw_trade_levels(self, order_info: dict, timeframe_minutes: int):
        if not order_info: return
        open_price = order_info.get('open_price')
        sl_price = order_info.get('sl')
        if open_price:
            pen = pg.mkPen('#00FFFF', style=pg.QtCore.Qt.DashLine, width=2)
            line = InfiniteLine(pos=open_price, angle=0, movable=False, pen=pen, label=f'Entry: {open_price}', labelOpts={'position':0.95, 'color': '#00FFFF', 'movable': True, 'fill': (30, 30, 30, 200)})
            self.main_plot.addItem(line)
            self.items_to_clear.append(line)
        if sl_price:
            pen = pg.mkPen('#FF4500', style=pg.QtCore.Qt.DashLine, width=2)
            line = InfiniteLine(pos=sl_price, angle=0, movable=False, pen=pen, label=f'SL: {sl_price}', labelOpts={'position':0.95, 'color': '#FF4500', 'movable': True, 'fill': (30, 30, 30, 200)})
            self.main_plot.addItem(line)
            self.items_to_clear.append(line)
        open_time_str = order_info.get('open_time')
        if open_time_str and timeframe_minutes and self.candles:
            try:
                try:
                    open_time_dt = datetime.strptime(open_time_str, '%Y.%m.%d %H:%M:%S')
                except ValueError:
                    open_time_dt = datetime.strptime(open_time_str, '%Y.%m.%d %H:%M')
                if timeframe_minutes >= 1440:
                    candle_start_dt = open_time_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                elif timeframe_minutes >= 60:
                    hours = timeframe_minutes // 60
                    new_hour = (open_time_dt.hour // hours) * hours
                    candle_start_dt = open_time_dt.replace(hour=new_hour, minute=0, second=0, microsecond=0)
                else:
                    new_minute = (open_time_dt.minute // timeframe_minutes) * timeframe_minutes
                    candle_start_dt = open_time_dt.replace(minute=new_minute, second=0, microsecond=0)
                candle_time_str = candle_start_dt.strftime('%Y.%m.%d %H:%M')
                entry_idx = self._find_candle_index(self.candles, candle_time_str)
                if entry_idx != -1:
                    is_buy = 'buy' in order_info.get('type', '').lower()
                    entry_candle = self.candles[entry_idx]
                    view_range = self.main_plot.vb.viewRange()
                    y_range = view_range[1] if view_range and view_range[1] else None
                    if y_range and y_range[1] != y_range[0]:
                        y_offset = (y_range[1] - y_range[0]) * 0.08
                    else:
                        y_offset = (entry_candle['high'] - entry_candle['low']) * 0.7
                    if is_buy:
                        symbol = 't1'
                        brush = pg.mkBrush(color=(0, 255, 0, 220))
                        y_pos = entry_candle['low'] - y_offset
                    else:
                        symbol = 't'
                        brush = pg.mkBrush(color=(255, 0, 0, 220))
                        y_pos = entry_candle['high'] + y_offset
                    arrow_marker = pg.ScatterPlotItem(
                        x=[entry_idx],
                        y=[y_pos],
                        symbol=symbol,
                        brush=brush,
                        size=15,
                        pen=None
                    )
                    self.main_plot.addItem(arrow_marker)
                    self.items_to_clear.append(arrow_marker)
            except (ValueError, TypeError, IndexError) as e:
                logging.warning(f"Could not parse open_time '{open_time_str}' to mark entry candle: {e}")
class ChartWindow(QMainWindow):
    data_loaded = pyqtSignal(object, str)
    status_updated = pyqtSignal(str)
    def __init__(self, ticket_id: int):
        super().__init__()
        if not ticket_id: raise ValueError("Ticket ID is required.")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.ticket_id = ticket_id
        self.chart_view = ChartView()
        self.chart_model = ChartDataModel()
        self.setWindowTitle(f"Chart Viewer - Ticket {self.ticket_id}")
        self.setGeometry(150, 150, 1800, 900)
        self.setWindowIcon(QIcon(":/icons/logo.png"))
        self.setCentralWidget(self.chart_view)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.data_loaded.connect(self.on_data_loaded)
        self.status_updated.connect(self.on_status_update)
    def _get_tf_string(self, minutes: int) -> str:
        if not isinstance(minutes, int) or minutes <= 0: return ""
        if minutes >= 43200: return f"MN{minutes // 43200}"
        if minutes >= 10080: return f"W{minutes // 10080}"
        if minutes >= 1440: return f"D{minutes // 1440}"
        if minutes >= 60: return f"H{minutes // 60}"
        return f"M{minutes}"
    def on_status_update(self, message: str):
        self.status_bar.showMessage(message)
    def on_data_loaded(self, model: ChartDataModel, window_title: str):
        self.setWindowTitle(window_title)
        self.status_updated.emit("Rendering chart...")
        self.chart_view.update_view(model)
        self.status_updated.emit("Load complete.")
    async def load_data(self):
        try:
            self.status_updated.emit("Initializing chart...")
            if not mt4_bridge._initialized:
                raise RuntimeError("MT4 Bridge is not initialized.")
            self.status_updated.emit(f"Fetching details for ticket {self.ticket_id}...")
            order_details = order_db_manager.get_order_details(self.ticket_id)
            if not order_details: raise ValueError(f"Could not find order details for ticket {self.ticket_id}.")
            self.chart_model.ticket = self.ticket_id
            self.chart_model.symbol = order_details.get('symbol')
            self.chart_model.timeframe = order_details.get('signal_tf')
            self.chart_model.order_info = order_details
            if not all([self.chart_model.symbol, self.chart_model.timeframe]):
                raise ValueError("Order details incomplete (symbol or signal_tf).")
            tf_string = self._get_tf_string(self.chart_model.timeframe)
            window_title = f"{self.chart_model.symbol}, {tf_string} - Ticket {self.ticket_id}"
            self.status_updated.emit(f"Loading {self.chart_model.symbol} {tf_string} candles...")
            candles_resp = await tool_market.get_historical_candles(self.chart_model.symbol, self.chart_model.timeframe, 250)
            if candles_resp.get('status') != 'success':
                raise IOError(f"Failed to load candle data: {candles_resp.get('message')}")
            self.chart_model.candles = candles_resp.get('data', [])
            if not self.chart_model.candles: raise ValueError("No candle data received.")
            self.status_updated.emit("Analyzing patterns and indicators...")
            candle_len = len(self.chart_model.candles)
            tasks = [
                tool_patterns.scan_for_all_price_action_history(self.chart_model.symbol, self.chart_model.timeframe, candle_len),
                tool_patterns.scan_for_all_structures_history(self.chart_model.symbol, self.chart_model.timeframe, candle_len),
                tool_utility.calculate_ema(self.chart_model.candles, period=89),
                tool_utility.calculate_rsi(self.chart_model.candles, period=14),
                tool_utility.calculate_bbands(self.chart_model.candles, period=20, std_dev=2.0),
                tool_utility.calculate_vegas_tunnel(self.chart_model.candles)
            ]
            pa_res, struct_res, ema_res, rsi_res, bbands_res, vegas_res = await asyncio.gather(*tasks)
            self.chart_model.patterns['price_action'] = pa_res.get('data')
            self.chart_model.patterns['structures'] = struct_res.get('data')
            self.chart_model.indicators['ema'] = {'data': ema_res.get('data')}
            self.chart_model.indicators['rsi'] = {'data': rsi_res.get('data')}
            self.chart_model.indicators['bbands'] = {'data': bbands_res.get('data')}
            self.chart_model.indicators['vegas'] = {'data': vegas_res.get('data')}
            try:
                self.data_loaded.emit(self.chart_model, window_title)
            except RuntimeError as e:
                if 'deleted' in str(e).lower():
                    logger.warning(f"Chart window for ticket {self.ticket_id} was closed before data loading finished. Signal emission skipped.")
                else:
                    raise
        except asyncio.CancelledError:
            logger.info(f"Chart loading for ticket {self.ticket_id} was cancelled because the window was closed.")
        except Exception as e:
            error_msg = f"Failed to load chart data for ticket {self.ticket_id}: {e}"
            logging.error(error_msg, exc_info=True)
            try:
                self.status_updated.emit(f"Error loading chart: {e}")
            except RuntimeError as re:
                if 'deleted' in str(re).lower():
                    logger.warning(f"Chart window for ticket {self.ticket_id} closed before error could be displayed.")
                else:
                    raise
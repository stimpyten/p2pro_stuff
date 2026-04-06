# touch_tester.py
from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.graphics import Color, Rectangle
from kivy.core.window import Window

class TouchTesterLayout(FloatLayout):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.coord_label = Label(
            text='Bitte den Bildschirm berühren.\nKoordinaten werden in der Konsole ausgegeben.',
            size_hint=(None, None),
            size=(500, 60),
            pos_hint={'center_x': 0.5, 'top': 0.98}
        )
        self.add_widget(self.coord_label)

    def on_touch_down(self, touch):
        # --- NEU: KOORDINATEN IN DER KONSOLE AUSGEBEN ---
        print(f"Touch-Ereignis bei (X={int(touch.x)}, Y={int(touch.y)})")
        # ---------------------------------------------

        # Aktualisiere den Text des Labels
        self.coord_label.text = f"Kivy Touch @ ({int(touch.x)}, {int(touch.y)})"

        # Lösche den vorherigen roten Punkt
        self.canvas.remove_group('marker')

        # Zeichne einen neuen roten Punkt an die Kivy-Position
        with self.canvas:
            Color(1, 0, 0, 1) # Rot
            Rectangle(pos=(touch.x - 10, touch.y - 10), size=(20, 20), group='marker')

        return True

    # Wir fügen auch on_touch_move hinzu, um das Ziehen besser zu sehen
    def on_touch_move(self, touch):
        # --- NEU: KOORDINATEN BEIM ZIEHEN AUSGEBEN ---
        print(f"Touch-Bewegung zu (X={int(touch.x)}, Y={int(touch.y)})")
        # ------------------------------------------

        # Aktualisiere Label und Punkt auch beim Ziehen
        self.coord_label.text = f"Kivy Touch @ ({int(touch.x)}, {int(touch.y)})"
        self.canvas.remove_group('marker')
        with self.canvas:
            Color(1, 0, 0, 1) # Rot
            Rectangle(pos=(touch.x - 10, touch.y - 10), size=(20, 20), group='marker')
        
        return True

class TouchTesterApp(App):
    def build(self):
        # Stellen Sie sicher, dass dies die Fenstergröße Ihrer Haupt-App ist
        Window.size = Window.system_size
        Window.fullscreen = 'auto'
        return TouchTesterLayout()

if __name__ == "__main__":
    TouchTesterApp().run()
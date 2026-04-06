from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.core.window import Window

from P2Pro.screenshot_viewer import ScreenshotViewerScreen
from P2Pro.video_viewer import VideoViewerScreen

class MenuScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation='vertical', spacing=40, padding=60)
        btn1 = Button(text="Screenshots durchsuchen", font_size=32, size_hint=(1, 0.3))
        btn2 = Button(text="Videos durchsuchen", font_size=32, size_hint=(1, 0.3))
        btn_exit = Button(text="Beenden", font_size=32, size_hint=(1, 0.2), background_color=(0.6,0,0,1))
        btn1.bind(on_press=self.go_screenshots)
        btn2.bind(on_press=self.go_videos)
        btn_exit.bind(on_press=self.exit_app)
        layout.add_widget(btn1)
        layout.add_widget(btn2)
        layout.add_widget(btn_exit)
        self.add_widget(layout)

    def go_screenshots(self, *args):
        self.manager.current = 'screenshots'

    def go_videos(self, *args):
        self.manager.current = 'videos'

    def exit_app(self, *args):
        App.get_running_app().stop()

class MainViewerApp(App):
    def build(self):
        # --- ANPASSUNG FÜR TOUCHSCREEN ---
        Window.size = Window.system_size
        Window.fullscreen = 'auto'  # <-- Vollbild robust aktivieren
        
        sm = ScreenManager()
        sm.add_widget(MenuScreen(name='menu'))
        sm.add_widget(ScreenshotViewerScreen(name='screenshots'))
        sm.add_widget(VideoViewerScreen(name='videos'))
        sm.current = 'menu'
        return sm

if __name__ == "__main__":
    MainViewerApp().run()
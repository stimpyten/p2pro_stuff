from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.screenmanager import Screen, ScreenManager

from P2Pro.screenshot_viewer_refactored import ScreenshotViewerScreen
from P2Pro.video_viewer_refactored import VideoViewerScreen


class MenuScreen(Screen):
    def __init__(self, screenshots_dir: str = "./screenshots", videos_dir: str = "./videos", **kwargs):
        super().__init__(**kwargs)
        self.screenshots_dir = screenshots_dir
        self.videos_dir = videos_dir

        layout = BoxLayout(orientation="vertical", spacing=40, padding=60)
        btn1 = Button(text="Screenshots durchsuchen", font_size=32, size_hint=(1, 0.3))
        btn2 = Button(text="Videos durchsuchen", font_size=32, size_hint=(1, 0.3))
        btn_exit = Button(text="Beenden", font_size=32, size_hint=(1, 0.2), background_color=(0.6, 0, 0, 1))

        btn1.bind(on_press=self.open_screenshots)
        btn2.bind(on_press=self.open_videos)
        btn_exit.bind(on_press=lambda *a: App.get_running_app().stop())

        layout.add_widget(btn1)
        layout.add_widget(btn2)
        layout.add_widget(btn_exit)
        self.add_widget(layout)

    def open_screenshots(self, *args):
        self.manager.current = "screenshots"

    def open_videos(self, *args):
        self.manager.current = "videos"


class ViewerApp(App):
    def build(self):
        Window.fullscreen = "auto"
        screenshots_dir = "./screenshots"
        videos_dir = "./videos"

        sm = ScreenManager()
        sm.add_widget(MenuScreen(name="menu", screenshots_dir=screenshots_dir, videos_dir=videos_dir))
        sm.add_widget(ScreenshotViewerScreen(name="screenshots", screenshots_dir=screenshots_dir, videos_dir=videos_dir))
        sm.add_widget(VideoViewerScreen(name="videos", screenshots_dir=screenshots_dir, videos_dir=videos_dir))
        return sm


if __name__ == "__main__":
    ViewerApp().run()

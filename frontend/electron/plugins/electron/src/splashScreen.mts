import { join } from "node:path";

import { app, nativeTheme, WebContentsView } from "./app.mjs";
import { mainWindow } from "./desktop.mjs";

type Theme = "light" | "dark";

/** The page's `--background` in each theme, which the window shows before the page paints. */
const BACKGROUND: Record<Theme, string> = { light: "#ffffff", dark: "#020618" };

const systemTheme = (): Theme => (nativeTheme.shouldUseDarkColors ? "dark" : "light");

/**
 * What `@capacitor/splash-screen` does on a phone, for the calls the app
 * makes: the splash laid over the window while the page reloads into an
 * update, until the new page hides it. The launch splash is the platform's
 * own window, closed when the page first paints.
 */
export class SplashScreen {
  static __capacitorElectronPlugin = { name: "SplashScreen", methods: ["show", "hide"] };

  private dismiss: (() => void) | null = null;

  /** Every window starts in the computer's theme, so its first frame is not white. */
  load() {
    app.on("browser-window-created", (_event, window) => {
      window.setBackgroundColor(BACKGROUND[systemTheme()]);
    });
  }

  async show() {
    const window = mainWindow();
    if (!window) {
      return;
    }
    // The page's own theme, which may not be the computer's.
    const theme: Theme = await window.webContents
      .executeJavaScript('document.documentElement.classList.contains("dark")')
      .then((dark: boolean) => (dark ? "dark" : "light"))
      .catch(systemTheme);
    if (this.dismiss) {
      return;
    }
    window.setBackgroundColor(BACKGROUND[theme]);

    const view = new WebContentsView({
      webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false },
    });
    view.setBackgroundColor(BACKGROUND[theme]);
    view.webContents.on("will-navigate", (event) => event.preventDefault());
    view.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    const fit = () => {
      const [width, height] = window.getContentSize();
      view.setBounds({ x: 0, y: 0, width, height });
    };
    fit();
    window.on("resize", fit);
    window.contentView.addChildView(view);
    void view.webContents
      .loadFile(join(app.getAppPath(), "assets", "splash.html"), { hash: theme })
      .catch(() => {
        // The view's background still covers the reload.
      });

    this.dismiss = () => {
      window.off("resize", fit);
      if (!window.isDestroyed()) {
        window.contentView.removeChildView(view);
      }
      view.webContents.close();
    };
  }

  async hide() {
    this.dismiss?.();
    this.dismiss = null;
  }
}

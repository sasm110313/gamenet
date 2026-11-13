//go:build windows

package main

import (
	"crypto/tls"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"

	"github.com/jchv/go-webview2"
	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

const serverURL = "https://127.0.0.1:19443/"

func main() {
	// Set WebView2 to ignore self-signed SSL certificate on local server
	_ = os.Setenv(
		"WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
		"--ignore-certificate-errors --allow-insecure-localhost --disable-features=Translate,PrivacySandboxSettings4",
	)

	exePath, err := os.Executable()
	if err != nil {
		exePath = "."
	}
	exeDir := filepath.Dir(exePath)
	rootDir := findRootDir(exeDir)

	if !isServerRunning(serverURL) {
		startBackgroundServer(exeDir, rootDir)

		ready := false
		for i := 0; i < 40; i++ {
			time.Sleep(500 * time.Millisecond)
			if isServerRunning(serverURL) {
				ready = true
				break
			}
		}

		if !ready {
			logPath := filepath.Join(rootDir, "backend", "data", "server.log")
			showErrorDialog(
				"بازی سرای رهرو - خطا در راه‌اندازی سرور",
				fmt.Sprintf(
					"سرور محلی روی پورت 19443 پاسخ نداد.\r\n\r\nلطفاً برنامه را با دسترسی Administrator اجرا کنید یا فایل گزارش زیر را بررسی نمایید:\r\n%s",
					logPath,
				),
			)
			return
		}
	}

	openStandaloneApp(serverURL)
}

func showErrorDialog(title, text string) {
	u32 := windows.NewLazySystemDLL("user32.dll")
	msgBox := u32.NewProc("MessageBoxW")
	tPtr, _ := windows.UTF16PtrFromString(title)
	mPtr, _ := windows.UTF16PtrFromString(text)
	// MB_OK | MB_ICONERROR | MB_RTLREADING
	_, _, _ = msgBox.Call(0, uintptr(unsafe.Pointer(mPtr)), uintptr(unsafe.Pointer(tPtr)), 0x00000010)
}

func findRootDir(startDir string) string {
	dir := startDir
	for i := 0; i < 4; i++ {
		if fileExists(filepath.Join(dir, "backend", "manage.py")) {
			return dir
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return startDir
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	return !info.IsDir()
}

func isServerRunning(url string) bool {
	tr := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}
	client := &http.Client{
		Transport: tr,
		Timeout:   1000 * time.Millisecond,
	}
	resp, err := client.Get(url)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode > 0
}

func startBackgroundServer(exeDir, rootDir string) {
	// 1. Try starting Windows Service first if registered
	scCmd := exec.Command("sc.exe", "start", "GameNetServer")
	scCmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
	if err := scCmd.Run(); err == nil {
		for i := 0; i < 16; i++ {
			time.Sleep(500 * time.Millisecond)
			if isServerRunning(serverURL) {
				return
			}
		}
	}

	// 2. Fallback: start bundled GameNet_Service.exe --foreground hidden
	svcCandidates := []string{
		filepath.Join(exeDir, "GameNet_Service.exe"),
		filepath.Join(rootDir, "GameNet_Service.exe"),
		filepath.Join(rootDir, "deploy", "windows", "GameNet_Service.exe"),
	}
	for _, svcExe := range svcCandidates {
		if fileExists(svcExe) {
			cmd := exec.Command(svcExe, "--foreground")
			cmd.Dir = filepath.Dir(svcExe)
			cmd.SysProcAttr = &syscall.SysProcAttr{
				HideWindow:    true,
				CreationFlags: windows.CREATE_NO_WINDOW | windows.DETACHED_PROCESS,
			}
			if err := cmd.Start(); err == nil {
				return
			}
		}
	}

	// 3. Final fallback: direct bundled python execution
	pyExe := filepath.Join(rootDir, "deploy", "windows", "python", "python.exe")
	if !fileExists(pyExe) {
		pyExe = filepath.Join(rootDir, "backend", "python", "python.exe")
	}
	if !fileExists(pyExe) {
		pyExe = "python.exe"
	}

	cmd := exec.Command(
		pyExe,
		"-m", "uvicorn", "gamenet.asgi:application",
		"--app-dir", filepath.Join(rootDir, "backend"),
		"--host", "0.0.0.0", "--port", "19443",
		"--ssl-keyfile", filepath.Join(rootDir, "dev", "certs", "edge.key"),
		"--ssl-certfile", filepath.Join(rootDir, "dev", "certs", "edge.pem"),
		"--ws", "websockets",
	)
	cmd.Dir = filepath.Join(rootDir, "backend")
	cmd.Env = append(
		os.Environ(),
		"GAMENET_ROLE=edge",
		"DJANGO_SETTINGS_MODULE=gamenet.settings.edge",
		"PYTHONUTF8=1",
		"CERTS="+filepath.Join(rootDir, "dev", "certs"),
		"DJANGO_STATIC_ROOT="+filepath.Join(rootDir, ".artifacts", "static"),
	)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: windows.CREATE_NO_WINDOW | windows.DETACHED_PROCESS,
	}
	_ = cmd.Start()
}

func isWebView2Available() bool {
	const webView2Guid = `{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`
	checks := []struct {
		root registry.Key
		path string
	}{
		{registry.LOCAL_MACHINE, `SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\` + webView2Guid},
		{registry.LOCAL_MACHINE, `SOFTWARE\Microsoft\EdgeUpdate\Clients\` + webView2Guid},
		{registry.CURRENT_USER, `Software\Microsoft\EdgeUpdate\Clients\` + webView2Guid},
	}
	for _, c := range checks {
		k, err := registry.OpenKey(c.root, c.path, registry.QUERY_VALUE)
		if err == nil {
			pv, _, err2 := k.GetStringValue("pv")
			_ = k.Close()
			if err2 == nil && strings.TrimSpace(pv) != "" {
				return true
			}
		}
	}
	return false
}

func openStandaloneApp(url string) {
	dataDir := filepath.Join(os.Getenv("APPDATA"), "GameNet", "ServerProfile")
	_ = os.MkdirAll(dataDir, 0755)

	if isWebView2Available() {
		w := webview2.NewWithOptions(webview2.WebViewOptions{
			Debug:     false,
			AutoFocus: true,
			DataPath:  dataDir,
			WindowOptions: webview2.WindowOptions{
				Title:  "بازی سرای رهرو - پنل مدیریت سالن (GameNet Server)",
				Width:  1366,
				Height: 850,
				Center: true,
			},
		})
		if w != nil {
			defer w.Destroy()
			w.SetSize(1366, 850, webview2.HintNone)
			w.Navigate(url)
			w.Run()
			return
		}
	}

	// Fallback for Windows 10 LTSB/LTSC or older builds without WebView2 runtime:
	// Launch in isolated borderless app window via Edge/Chrome
	appArgs := []string{
		"--app=" + url,
		"--ignore-certificate-errors",
		"--allow-insecure-localhost",
		"--no-first-run",
		"--user-data-dir=" + dataDir,
	}
	browserPaths := []string{
		`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`,
		`C:\Program Files\Microsoft\Edge\Application\msedge.exe`,
		`C:\Program Files\Google\Chrome\Application\chrome.exe`,
		`C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`,
	}
	for _, p := range browserPaths {
		if fileExists(p) {
			cmd := exec.Command(p, appArgs...)
			if err := cmd.Start(); err == nil {
				return
			}
		}
	}

	for _, name := range []string{"msedge.exe", "chrome.exe"} {
		if path, err := exec.LookPath(name); err == nil {
			cmd := exec.Command(path, appArgs...)
			if err := cmd.Start(); err == nil {
				return
			}
		}
	}

	// Final fallback to system default browser
	_ = exec.Command("cmd.exe", "/c", "start", "", url).Start()
}

package main

import (
	"crypto/tls"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

func main() {
	fmt.Println("=======================================================")
	fmt.Println("       GameNet Salon Management Server (Windows)       ")
	fmt.Println("             مدیریت سالن گیم‌نت - نسخه ویندوز          ")
	fmt.Println("=======================================================")
	fmt.Println()

	// Locate repo root directory
	exePath, err := os.Executable()
	if err != nil {
		exePath = "."
	}
	exeDir := filepath.Dir(exePath)

	// Determine root directory (either current dir, parent dir, or grand-parent)
	rootDir := exeDir
	if fileExists(filepath.Join(rootDir, "backend", "manage.py")) {
		// rootDir is current
	} else if fileExists(filepath.Join(rootDir, "..", "backend", "manage.py")) {
		rootDir = filepath.Clean(filepath.Join(rootDir, ".."))
	} else if fileExists(filepath.Join(rootDir, "..", "..", "backend", "manage.py")) {
		rootDir = filepath.Clean(filepath.Join(rootDir, "..", ".."))
	}

	backendDir := filepath.Join(rootDir, "backend")
	runBat := filepath.Join(rootDir, "deploy", "windows", "run_server.bat")

	serverURL := "https://127.0.0.1:19443/"

	// Check if server is already running
	fmt.Print("[1/3] بررسی وضعیت سرور گیم‌نت... ")
	if isServerRunning(serverURL) {
		fmt.Println("فعال است! (Server is running)")
	} else {
		fmt.Println("در حال راه‌اندازی...")

		// Try starting Windows Service first
		scCmd := exec.Command("sc", "start", "GameNetServer")
		_ = scCmd.Run()

		time.Sleep(1 * time.Second)

		if !isServerRunning(serverURL) {
			// Start server via run_server.bat in background
			if fileExists(runBat) {
				fmt.Println("[2/3] اجرای مستقیم سرور در پس‌زمینه...")
				cmd := exec.Command("cmd.exe", "/c", "start", "/b", runBat)
				cmd.Dir = backendDir
				_ = cmd.Start()
			} else {
				// Fallback to python
				pyExe := filepath.Join(backendDir, ".venv", "Scripts", "python.exe")
				if !fileExists(pyExe) {
					pyExe = "python"
				}
				cmd := exec.Command("cmd.exe", "/c", "start", "/b", pyExe, "-m", "uvicorn", "gamenet.asgi:application", "--host", "0.0.0.0", "--port", "19443")
				cmd.Dir = backendDir
				_ = cmd.Start()
			}
		}

		// Wait for server to be responsive
		fmt.Print("      در انتظار پاسخ‌گویی سرور")
		started := false
		for i := 0; i < 15; i++ {
			time.Sleep(1 * time.Second)
			fmt.Print(".")
			if isServerRunning(serverURL) {
				started = true
				break
			}
		}
		fmt.Println()

		if started {
			fmt.Println("      سرور سالن با موفقیت راه‌اندازی شد!")
		} else {
			fmt.Println("      [هشدار] راه‌اندازی سرور طول کشید؛ با این حال پنل باز می‌شود...")
		}
	}

	// Open admin management dashboard
	fmt.Println("[3/3] باز کردن پنل مدیریت سالن (10 سیستم)...")
	openBrowserApp(serverURL)

	fmt.Println()
	fmt.Println("=======================================================")
	fmt.Println("  پنل مدیریت سالن باز شد: " + serverURL)
	fmt.Println("  - کلاینت‌ها (سیستم‌های ۱ تا ۱۰) به صورت خودکار متصل می‌شوند.")
	fmt.Println("  - در صورت اتصال به اینترنت، اطلاعات با سرور آنلاین همگام می‌شود.")
	fmt.Println("=======================================================")
	fmt.Println()
	fmt.Println("برای بستن این پنجره دکمه Enter را بزنید (سرور در پس‌زمینه به کار خود ادامه می‌دهد).")
	var dummy string
	fmt.Scanln(&dummy)
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
		Timeout:   1200 * time.Millisecond,
	}
	resp, err := client.Get(url)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode > 0
}

func openBrowserApp(url string) {
	// 1. Try Microsoft Edge in standalone app window
	edgePaths := []string{
		`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`,
		`C:\Program Files\Microsoft\Edge\Application\msedge.exe`,
		"msedge.exe",
	}
	for _, p := range edgePaths {
		if strings.HasSuffix(p, ".exe") && (fileExists(p) || p == "msedge.exe") {
			cmd := exec.Command(p, "--app="+url, "--ignore-certificate-errors", "--no-first-run")
			if err := cmd.Start(); err == nil {
				return
			}
		}
	}

	// 2. Try Google Chrome in standalone app window
	chromePaths := []string{
		`C:\Program Files\Google\Chrome\Application\chrome.exe`,
		`C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`,
		os.Getenv("LOCALAPPDATA") + `\Google\Chrome\Application\chrome.exe`,
		"chrome.exe",
	}
	for _, p := range chromePaths {
		if strings.HasSuffix(p, ".exe") && (fileExists(p) || p == "chrome.exe") {
			cmd := exec.Command(p, "--app="+url, "--ignore-certificate-errors", "--no-first-run")
			if err := cmd.Start(); err == nil {
				return
			}
		}
	}

	// 3. Fallback to default browser
	_ = exec.Command("cmd.exe", "/c", "start", url).Start()
}

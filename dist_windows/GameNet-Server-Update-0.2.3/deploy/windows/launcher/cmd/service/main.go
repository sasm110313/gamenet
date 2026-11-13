//go:build windows

package main

import (
	"crypto/rand"
	"crypto/tls"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/mgr"
)

const serviceName = "GameNetServer"
const serviceDisplay = "GameNet Salon Server (بازی سرای رهرو)"
const serviceDesc = "سرویس محلی سرور مدیریت گیم‌نت بازی سرای رهرو - ارتباط کلاینت‌ها و همگام‌سازی ابری"
const serverHealthURL = "https://127.0.0.1:19443/"

func main() {
	isSvc, err := svc.IsWindowsService()
	if err == nil && isSvc {
		runAsService()
		return
	}

	args := os.Args[1:]
	mode := "--help"
	if len(args) > 0 {
		mode = strings.ToLower(strings.TrimSpace(args[0]))
	}

	switch mode {
	case "--setup":
		if err := runSetup(); err != nil {
			fmt.Fprintf(os.Stderr, "[ERROR] Setup failed: %v\n", err)
			os.Exit(1)
		}
	case "--foreground":
		runForeground()
	case "--ensure-running":
		if err := ensureRunning(); err != nil {
			fmt.Fprintf(os.Stderr, "[ERROR] %v\n", err)
			os.Exit(1)
		}
	case "--uninstall":
		if err := runUninstall(); err != nil {
			fmt.Fprintf(os.Stderr, "[ERROR] %v\n", err)
			os.Exit(1)
		}
	case "--change-admin":
		if err := runChangeAdmin(args[1:]); err != nil {
			fmt.Fprintf(os.Stderr, "[ERROR] %v\n", err)
			os.Exit(1)
		}
	default:
		if err := ensureRunning(); err != nil {
			fmt.Fprintf(os.Stderr, "[ERROR] %v\n", err)
			os.Exit(1)
		}
	}
}

func exePathAndRoot() (string, string) {
	exe, err := os.Executable()
	if err != nil {
		exe, _ = filepath.Abs(os.Args[0])
	}
	dir := filepath.Dir(exe)
	root := dir
	for i := 0; i < 4; i++ {
		if fileExists(filepath.Join(root, "backend", "manage.py")) {
			return exe, root
		}
		parent := filepath.Dir(root)
		if parent == root {
			break
		}
		root = parent
	}
	return exe, dir
}

func fileExists(p string) bool {
	info, err := os.Stat(p)
	return err == nil && !info.IsDir()
}

func findPython(rootDir string) string {
	candidates := []string{
		filepath.Join(rootDir, "deploy", "windows", "python", "python.exe"),
		filepath.Join(rootDir, "backend", "python", "python.exe"),
		filepath.Join(rootDir, "backend", ".venv", "Scripts", "python.exe"),
	}
	for _, c := range candidates {
		if fileExists(c) {
			return c
		}
	}
	return "python.exe"
}

func randomHex(nBytes int) string {
	b := make([]byte, nBytes)
	if _, err := rand.Read(b); err != nil {
		return fmt.Sprintf("gamenet-%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(b)
}

func ensureEnvAndDirs(rootDir string) error {
	dataDir := filepath.Join(rootDir, "backend", "data")
	artDir := filepath.Join(rootDir, ".artifacts")
	if err := os.MkdirAll(dataDir, 0755); err != nil {
		return err
	}
	if err := os.MkdirAll(artDir, 0755); err != nil {
		return err
	}

	envPath := filepath.Join(rootDir, ".env")
	needsEnv := !fileExists(envPath)
	if !needsEnv {
		if raw, err := os.ReadFile(envPath); err != nil || !strings.Contains(string(raw), "DJANGO_SECRET_KEY=") {
			needsEnv = true
		}
	}
	if needsEnv {
		secret := randomHex(32)
		content := strings.Join([]string{
			"GAMENET_ROLE=edge",
			"GAMENET_ENV=prod",
			"DJANGO_SECRET_KEY=" + secret,
			"DJANGO_DEBUG=0",
			"DJANGO_ALLOWED_HOSTS=*",
			"DJANGO_SECURE_COOKIES=0",
			"CHANNEL_LAYER=memory",
			"EDGE_NAME=سالن اصلی",
			"EDGE_LAN_BIND=0.0.0.0",
			"EDGE_LAN_PORT=19443",
			"EDGE_DISCOVERY_PORT=19445",
			"CLOUD_BASE_URL=https://gamenet.hammasjedy.ir",
			"CLOUD_WS_URL=wss://gamenet.hammasjedy.ir/ws/edge/",
			"EDGE_CREDENTIALS_FILE=.artifacts/edge-credentials.json",
			"EDGE_SYNC_INTERVAL_SECONDS=2",
			"EDGE_HEARTBEAT_SECONDS=5",
			"DEVICE_HEARTBEAT_SECONDS=10",
			"DEVICE_OFFLINE_AFTER_MISSED=3",
			"",
		}, "\r\n")
		if err := os.WriteFile(envPath, []byte(content), 0644); err != nil {
			return err
		}
	}
	return nil
}

func buildPythonEnv(rootDir string) []string {
	overrides := map[string]string{
		"GAMENET_ROLE":           "edge",
		"DJANGO_SETTINGS_MODULE": "gamenet.settings.edge",
		"PYTHONUTF8":             "1",
		"PYTHONIOENCODING":       "utf-8",
		"EDGE_LAN_BIND":          "0.0.0.0",
		"EDGE_LAN_PORT":          "19443",
		"EDGE_DISCOVERY_PORT":    "19445",
		"CERTS":                  filepath.Join(rootDir, "dev", "certs"),
		"DJANGO_STATIC_ROOT":     filepath.Join(rootDir, ".artifacts", "static"),
	}
	base := os.Environ()
	out := make([]string, 0, len(base)+len(overrides))
	for _, kv := range base {
		parts := strings.SplitN(kv, "=", 2)
		k := strings.ToUpper(parts[0])
		if _, found := overrides[k]; found {
			continue
		}
		out = append(out, kv)
	}
	for k, v := range overrides {
		out = append(out, k+"="+v)
	}
	return out
}

func openRotatingLog(logPath string) (*os.File, error) {
	if err := os.MkdirAll(filepath.Dir(logPath), 0755); err != nil {
		return nil, err
	}
	if info, err := os.Stat(logPath); err == nil && info.Size() > 5*1024*1024 {
		oldPath := logPath + ".old"
		_ = os.Remove(oldPath)
		_ = os.Rename(logPath, oldPath)
	}
	return os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
}

func logLine(w io.Writer, msg string) {
	if w == nil {
		return
	}
	line := fmt.Sprintf("[%s] %s\r\n", time.Now().Format("2006-01-02 15:04:05"), msg)
	_, _ = io.WriteString(w, line)
}

func runPythonTask(rootDir string, logOut io.Writer, extraArgs ...string) error {
	py := findPython(rootDir)
	backendDir := filepath.Join(rootDir, "backend")
	cmd := exec.Command(py, extraArgs...)
	cmd.Dir = backendDir
	cmd.Env = buildPythonEnv(rootDir)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
	if logOut != nil {
		cmd.Stdout = logOut
		cmd.Stderr = logOut
	}
	return cmd.Run()
}

func ensureBootstrapped(rootDir string, logOut io.Writer) error {
	logLine(logOut, "Running database migrations (gamenet.settings.edge)...")
	if err := runPythonTask(rootDir, logOut, "manage.py", "migrate", "--noinput", "--settings=gamenet.settings.edge"); err != nil {
		return fmt.Errorf("migrate failed: %w", err)
	}
	logLine(logOut, "Running bootstrap_edge...")
	if err := runPythonTask(rootDir, logOut, "manage.py", "bootstrap_edge", "--settings=gamenet.settings.edge"); err != nil {
		return fmt.Errorf("bootstrap_edge failed: %w", err)
	}
	return nil
}

func createKillJob() windows.Handle {
	job, err := windows.CreateJobObject(nil, nil)
	if err != nil {
		return 0
	}
	var info windows.JOBOBJECT_EXTENDED_LIMIT_INFORMATION
	info.BasicLimitInformation.LimitFlags = windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	_, _ = windows.SetInformationJobObject(
		job,
		windows.JobObjectExtendedLimitInformation,
		uintptr(unsafe.Pointer(&info)),
		uint32(unsafe.Sizeof(info)),
	)
	return job
}

func assignPidToJob(job windows.Handle, pid int) {
	if job == 0 || pid <= 0 {
		return
	}
	h, err := windows.OpenProcess(windows.PROCESS_SET_QUOTA|windows.PROCESS_TERMINATE, false, uint32(pid))
	if err != nil {
		return
	}
	defer windows.CloseHandle(h)
	_ = windows.AssignProcessToJobObject(job, h)
}

func killProcessTree(pid int) {
	if pid <= 0 {
		return
	}
	tk := exec.Command("taskkill.exe", "/F", "/T", "/PID", fmt.Sprintf("%d", pid))
	tk.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
	_ = tk.Run()
}

func runSupervisorLoop(rootDir string, stopCh <-chan struct{}) {
	_ = ensureEnvAndDirs(rootDir)
	logPath := filepath.Join(rootDir, "backend", "data", "server.log")
	logFile, _ := openRotatingLog(logPath)
	defer func() {
		if logFile != nil {
			_ = logFile.Close()
		}
	}()

	logLine(logFile, "GameNet Service supervisor starting...")

	if err := ensureBootstrapped(rootDir, logFile); err != nil {
		logLine(logFile, fmt.Sprintf("Bootstrap error (will still attempt server launch): %v", err))
	}

	py := findPython(rootDir)
	backendDir := filepath.Join(rootDir, "backend")
	certsDir := filepath.Join(rootDir, "dev", "certs")
	keyFile := filepath.Join(certsDir, "edge.key")
	certFile := filepath.Join(certsDir, "edge.pem")

	for {
		select {
		case <-stopCh:
			logLine(logFile, "Stop signal received; exiting supervisor.")
			return
		default:
		}

		// Rotate log cleanly across restarts
		if logFile != nil {
			if info, err := logFile.Stat(); err == nil && info.Size() > 5*1024*1024 {
				_ = logFile.Close()
				logFile, _ = openRotatingLog(logPath)
			}
		}

		args := []string{
			"-m", "uvicorn", "gamenet.asgi:application",
			"--app-dir", backendDir,
			"--host", "0.0.0.0",
			"--port", "19443",
			"--ws", "websockets",
			"--log-level", "info",
		}
		if fileExists(keyFile) && fileExists(certFile) {
			args = append(args, "--ssl-keyfile", keyFile, "--ssl-certfile", certFile)
		}

		cmd := exec.Command(py, args...)
		cmd.Dir = backendDir
		cmd.Env = buildPythonEnv(rootDir)
		cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
		if logFile != nil {
			cmd.Stdout = logFile
			cmd.Stderr = logFile
		}

		job := createKillJob()
		logLine(logFile, "Launching ASGI Uvicorn worker on 0.0.0.0:19443...")
		if err := cmd.Start(); err != nil {
			if job != 0 {
				_ = windows.CloseHandle(job)
			}
			logLine(logFile, fmt.Sprintf("Failed starting uvicorn: %v (retrying in 3s)", err))
			select {
			case <-stopCh:
				return
			case <-time.After(3 * time.Second):
				continue
			}
		}

		pid := cmd.Process.Pid
		assignPidToJob(job, pid)

		waitDone := make(chan error, 1)
		go func() {
			waitDone <- cmd.Wait()
		}()

		select {
		case <-stopCh:
			logLine(logFile, "Stopping ASGI worker due to service stop...")
			killProcessTree(pid)
			if job != 0 {
				_ = windows.CloseHandle(job)
			}
			select {
			case <-waitDone:
			case <-time.After(4 * time.Second):
			}
			return
		case err := <-waitDone:
			if job != 0 {
				_ = windows.CloseHandle(job)
			}
			logLine(logFile, fmt.Sprintf("ASGI worker exited (%v). Restarting in 2s...", err))
			select {
			case <-stopCh:
				return
			case <-time.After(2 * time.Second):
			}
		}
	}
}

type gnService struct {
	rootDir string
}

func (s *gnService) Execute(args []string, r <-chan svc.ChangeRequest, changes chan<- svc.Status) (ssec bool, errno uint32) {
	const cmdsAccepted = svc.AcceptStop | svc.AcceptShutdown
	changes <- svc.Status{State: svc.StartPending}

	stopCh := make(chan struct{})
	var stopOnce sync.Once
	closeStop := func() {
		stopOnce.Do(func() { close(stopCh) })
	}

	done := make(chan struct{})
	go func() {
		defer close(done)
		runSupervisorLoop(s.rootDir, stopCh)
	}()

	changes <- svc.Status{State: svc.Running, Accepts: cmdsAccepted}

loop:
	for {
		select {
		case c := <-r:
			switch c.Cmd {
			case svc.Interrogate:
				changes <- c.CurrentStatus
			case svc.Stop, svc.Shutdown:
				changes <- svc.Status{State: svc.StopPending}
				closeStop()
				break loop
			}
		case <-done:
			break loop
		}
	}

	select {
	case <-done:
	case <-time.After(6 * time.Second):
	}
	changes <- svc.Status{State: svc.Stopped}
	return false, 0
}

func runAsService() {
	_, rootDir := exePathAndRoot()
	_ = svc.Run(serviceName, &gnService{rootDir: rootDir})
}

func runForeground() {
	_, rootDir := exePathAndRoot()
	stopCh := make(chan struct{})
	sigCh := make(chan os.Signal, 2)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigCh
		close(stopCh)
	}()
	runSupervisorLoop(rootDir, stopCh)
}

func isServerHealthy() bool {
	tr := &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}
	client := &http.Client{Transport: tr, Timeout: 1200 * time.Millisecond}
	resp, err := client.Get(serverHealthURL)
	if err != nil {
		return false
	}
	_ = resp.Body.Close()
	return resp.StatusCode > 0
}

func waitForHealthy(timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if isServerHealthy() {
			return true
		}
		time.Sleep(500 * time.Millisecond)
	}
	return false
}

func configureFirewall() {
	cmds := [][]string{
		{"netsh", "advfirewall", "firewall", "delete", "rule", "name=GameNet Salon Server HTTPS"},
		{"netsh", "advfirewall", "firewall", "add", "rule", "name=GameNet Salon Server HTTPS", "dir=in", "action=allow", "protocol=TCP", "localport=19443"},
		{"netsh", "advfirewall", "firewall", "delete", "rule", "name=GameNet Salon Server Discovery"},
		{"netsh", "advfirewall", "firewall", "add", "rule", "name=GameNet Salon Server Discovery", "dir=in", "action=allow", "protocol=UDP", "localport=19445"},
	}
	for _, parts := range cmds {
		c := exec.Command(parts[0], parts[1:]...)
		c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
		_ = c.Run()
	}
}

func trustRootCert(rootDir string) {
	caPem := filepath.Join(rootDir, "dev", "certs", "ca.pem")
	if !fileExists(caPem) {
		return
	}
	c := exec.Command("certutil.exe", "-addstore", "-f", "Root", caPem)
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
	_ = c.Run()
}

func grantWritableDataDirs(rootDir string) {
	dirs := []string{
		filepath.Join(rootDir, "backend", "data"),
		filepath.Join(rootDir, "backend", ".runtime"),
		filepath.Join(rootDir, ".artifacts"),
	}
	for _, d := range dirs {
		_ = os.MkdirAll(d, 0755)
		c := exec.Command("icacls.exe", d, "/grant", "*S-1-5-32-545:(OI)(CI)M", "/T", "/Q")
		c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
		_ = c.Run()
	}
}

func stopAndRemoveService() error {
	m, err := mgr.Connect()
	if err != nil {
		return err
	}
	defer m.Disconnect()

	s, err := m.OpenService(serviceName)
	if err == nil {
		status, qErr := s.Query()
		if qErr == nil && status.State != svc.Stopped {
			_, _ = s.Control(svc.Stop)
			deadline := time.Now().Add(10 * time.Second)
			for time.Now().Before(deadline) {
				st, err2 := s.Query()
				if err2 != nil || st.State == svc.Stopped {
					break
				}
				time.Sleep(300 * time.Millisecond)
			}
		}
		_ = s.Delete()
		_ = s.Close()
		time.Sleep(800 * time.Millisecond)
	}
	return nil
}

func installAndStartService(exePath string) error {
	_ = stopAndRemoveService()

	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("failed opening SCM (admin privileges required): %w", err)
	}
	defer m.Disconnect()

	s, err := m.CreateService(
		serviceName,
		exePath,
		mgr.Config{
			DisplayName:  serviceDisplay,
			Description:  serviceDesc,
			StartType:    mgr.StartAutomatic,
			ErrorControl: mgr.ErrorNormal,
		},
	)
	if err != nil {
		return fmt.Errorf("CreateService failed: %w", err)
	}
	defer s.Close()

	_ = s.SetRecoveryActions([]mgr.RecoveryAction{
		{Type: mgr.ServiceRestart, Delay: 3 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 3 * time.Second},
		{Type: mgr.ServiceRestart, Delay: 5 * time.Second},
	}, 86400)

	if err := s.Start(); err != nil {
		return fmt.Errorf("StartService failed: %w", err)
	}
	return nil
}

func killResidualServerProcesses(rootDir string) {
	// Kill any python/uvicorn listening on 19443 or inside rootDir via PowerShell safely
	c := exec.Command("powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
		fmt.Sprintf(`$root = '%s'.ToLower(); `+
			`Get-Process python,GameNet_Server -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.ToLower().StartsWith($root) } | Stop-Process -Force -ErrorAction SilentlyContinue; `+
			`Get-NetTCPConnection -LocalPort 19443 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }`,
			strings.ReplaceAll(rootDir, "'", "''"),
		),
	)
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
	_ = c.Run()
}

func registerWatchdogTask(exePath string) {
	// Also keep a lightweight SYSTEM watchdog task every 2 minutes + logon task as an extra safety net
	cmds := [][]string{
		{"schtasks.exe", "/delete", "/tn", "GameNetSalonServer", "/f"},
		{"schtasks.exe", "/delete", "/tn", "GameNetServer_Boot", "/f"},
		{"schtasks.exe", "/delete", "/tn", "GameNetServer_Logon", "/f"},
		{"schtasks.exe", "/delete", "/tn", "GameNetServer_Watchdog", "/f"},
		{"schtasks.exe", "/create", "/tn", "GameNetServer_Watchdog", "/tr", fmt.Sprintf(`"%s" --ensure-running`, exePath), "/sc", "minute", "/mo", "2", "/ru", "SYSTEM", "/rl", "highest", "/f"},
	}
	for _, parts := range cmds {
		c := exec.Command(parts[0], parts[1:]...)
		c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
		_ = c.Run()
	}
}

func removeScheduledTasksAndFirewall() {
	cmds := [][]string{
		{"schtasks.exe", "/delete", "/tn", "GameNetSalonServer", "/f"},
		{"schtasks.exe", "/delete", "/tn", "GameNetServer_Boot", "/f"},
		{"schtasks.exe", "/delete", "/tn", "GameNetServer_Logon", "/f"},
		{"schtasks.exe", "/delete", "/tn", "GameNetServer_Watchdog", "/f"},
		{"netsh.exe", "advfirewall", "firewall", "delete", "rule", "name=GameNet Salon Server HTTPS"},
		{"netsh.exe", "advfirewall", "firewall", "delete", "rule", "name=GameNet Salon Server Discovery"},
	}
	for _, parts := range cmds {
		c := exec.Command(parts[0], parts[1:]...)
		c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
		_ = c.Run()
	}
}

func runSetup() error {
	exePath, rootDir := exePathAndRoot()
	if err := ensureEnvAndDirs(rootDir); err != nil {
		return err
	}
	setupLog, _ := openRotatingLog(filepath.Join(rootDir, "backend", "data", "setup.log"))
	defer func() {
		if setupLog != nil {
			_ = setupLog.Close()
		}
	}()

	var logOut io.Writer = os.Stdout
	if setupLog != nil {
		logOut = io.MultiWriter(os.Stdout, setupLog)
	}

	logLine(logOut, "Stopping any existing GameNet server processes...")
	_ = stopAndRemoveService()
	killResidualServerProcesses(rootDir)

	fmt.Println("[1/4] Initializing local database and stations (PC-01..PC-10)...")
	if err := ensureBootstrapped(rootDir, logOut); err != nil {
		return err
	}

	fmt.Println("[2/4] Configuring Windows Firewall, certificates and folder permissions...")
	configureFirewall()
	trustRootCert(rootDir)
	grantWritableDataDirs(rootDir)

	fmt.Println("[3/4] Installing Windows Service GameNetServer (auto-start on boot)...")
	if err := installAndStartService(exePath); err != nil {
		return err
	}
	registerWatchdogTask(exePath)

	fmt.Println("[4/4] Waiting for GameNet Server health check (https://127.0.0.1:19443/)...")
	if !waitForHealthy(25 * time.Second) {
		return fmt.Errorf("GameNet Server did not respond on 127.0.0.1:19443 within 25s (check backend\\data\\server.log)")
	}
	fmt.Println("[OK] GameNet Server installed, running as Windows Service, and healthy!")
	return nil
}

func ensureRunning() error {
	if isServerHealthy() {
		return nil
	}
	exePath, _ := exePathAndRoot()

	// Try starting Windows Service first
	if m, err := mgr.Connect(); err == nil {
		if s, err2 := m.OpenService(serviceName); err2 == nil {
			_ = s.Start()
			_ = s.Close()
		}
		_ = m.Disconnect()
		if waitForHealthy(15 * time.Second) {
			return nil
		}
	}

	// Fallback: start hidden foreground process
	cmd := exec.Command(exePath, "--foreground")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW | windows.DETACHED_PROCESS}
	if err := cmd.Start(); err != nil {
		return err
	}
	if !waitForHealthy(20 * time.Second) {
		return fmt.Errorf("server failed to start cleanly; see backend\\data\\server.log")
	}
	return nil
}

func runUninstall() error {
	_, rootDir := exePathAndRoot()
	_ = stopAndRemoveService()
	killResidualServerProcesses(rootDir)
	removeScheduledTasksAndFirewall()
	return nil
}

func runChangeAdmin(extraArgs []string) error {
	_, rootDir := exePathAndRoot()
	_ = ensureEnvAndDirs(rootDir)
	py := findPython(rootDir)
	args := append([]string{"manage.py", "change_admin"}, extraArgs...)
	cmd := exec.Command(py, args...)
	cmd.Dir = filepath.Join(rootDir, "backend")
	cmd.Env = buildPythonEnv(rootDir)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

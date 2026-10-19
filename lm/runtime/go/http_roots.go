// System trust roots, without SSL_CERT_FILE or SSL_CERT_DIR overrides.
package main

import (
	"crypto/x509"
	"os"
	"path/filepath"
	"runtime"
)

func httpSystemRoots() (*x509.CertPool, error) {
	// These platforms use their native certificate store, not Unix env paths.
	if runtime.GOOS == "darwin" || runtime.GOOS == "windows" {
		return x509.SystemCertPool()
	}
	files := []string{
		"/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
		"/etc/ssl/ca-bundle.pem", "/etc/pki/tls/cacert.pem",
		"/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem", "/etc/ssl/cert.pem",
	}
	dirs := []string{"/etc/ssl/certs", "/etc/pki/tls/certs"}
	switch runtime.GOOS {
	case "freebsd", "openbsd", "netbsd", "dragonfly":
		files = []string{"/usr/local/etc/ssl/cert.pem", "/etc/ssl/cert.pem",
			"/usr/local/share/certs/ca-root-nss.crt", "/etc/openssl/certs/ca-certificates.crt"}
		dirs = []string{"/etc/ssl/certs", "/usr/local/share/certs", "/etc/openssl/certs"}
	case "solaris", "illumos":
		files = []string{"/etc/certs/ca-certificates.crt", "/etc/ssl/certs/ca-certificates.crt", "/etc/ssl/cacert.pem"}
		dirs = []string{"/etc/certs/CA"}
	case "aix":
		files, dirs = []string{"/var/ssl/certs/ca-bundle.crt"}, []string{"/var/ssl/certs"}
	case "plan9":
		files, dirs = []string{"/sys/lib/tls/ca.pem"}, nil
	case "android":
		dirs = append(dirs, "/system/etc/security/cacerts", "/data/misc/keychain/certs-added")
	}
	roots := x509.NewCertPool()
	for _, file := range files {
		if data, err := os.ReadFile(file); err == nil {
			roots.AppendCertsFromPEM(data)
			break
		}
	}
	for _, dir := range dirs {
		entries, _ := os.ReadDir(dir)
		for _, entry := range entries {
			if data, err := os.ReadFile(filepath.Join(dir, entry.Name())); err == nil {
				roots.AppendCertsFromPEM(data)
			}
		}
	}
	return roots, nil
}

// System access prims: environment reads and non-recursive filesystem operations.
package main

import (
	"errors"
	"io/fs"
	"os"
	"sort"
	"strings"
	"syscall"
	"unicode/utf8"
)

func prim_env_lookup(name Value) Value {
	n := name.(string)
	if n == "" || strings.ContainsAny(n, "=\x00") {
		return V_None
	}
	v, ok := os.LookupEnv(n)
	if !ok {
		return V_None
	}
	return mkSome(toValidUTF8(v))
}

func prim_fs_append(path, text Value) Value {
	p := path.(string)
	f, err := os.OpenFile(p, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0o666)
	if err != nil {
		fsFail(p, err)
	}
	_, writeErr := f.WriteString(text.(string))
	closeErr := f.Close()
	if writeErr != nil {
		fsFail(p, writeErr)
	}
	if closeErr != nil {
		fsFail(p, closeErr)
	}
	return U
}

func prim_fs_entries(path Value) Value {
	p := path.(string)
	entries, err := os.ReadDir(p)
	if err != nil {
		fsFail(p, err)
	}
	names := make([]string, len(entries))
	for i, entry := range entries {
		name := entry.Name()
		if !utf8.ValidString(name) {
			fsFail(p, errors.New("invalid UTF-8 in directory entry"))
		}
		names[i] = name
	}
	// UTF-8 byte ordering agrees with code point ordering for valid strings.
	sort.Strings(names)
	return strList(names)
}

func prim_fs_is_dir(path Value) Value {
	p := path.(string)
	info, err := os.Stat(p)
	if err == nil {
		return info.IsDir()
	}
	if errors.Is(err, fs.ErrNotExist) || errors.Is(err, syscall.ENOTDIR) {
		return false
	}
	fsFail(p, err)
	return false
}

func prim_fs_make_dir(path Value) Value {
	p := path.(string)
	if err := os.Mkdir(p, 0o777); err != nil {
		fsFail(p, err)
	}
	return U
}

func prim_fs_remove(path Value) Value {
	p := path.(string)
	if err := os.Remove(p); err != nil {
		fsFail(p, err)
	}
	return U
}

func prim_fs_rename(from, to Value) Value {
	src, dst := from.(string), to.(string)
	if src == dst {
		fsFail(src, errors.New("source and destination are identical"))
	}
	info, err := os.Lstat(src)
	if err != nil {
		fsFail(src, err)
	}
	if info.IsDir() {
		if _, err := os.Lstat(dst); err == nil {
			fsFail(src, errors.New("destination exists"))
		} else if !errors.Is(err, fs.ErrNotExist) {
			fsFail(src, err)
		}
		if err := os.Rename(src, dst); err != nil {
			fsFail(src, err)
		}
	} else {
		// Creating the destination name fails atomically if it exists: a new
		// symlink for a symlink (portable, no link(2) dereferencing), else a hard link.
		if err := claimName(src, dst, info); err != nil {
			fsFail(src, err)
		}
		if err := os.Remove(src); err != nil {
			fsFail(src, err)
		}
	}
	return U
}

func claimName(src, dst string, info fs.FileInfo) error {
	if info.Mode()&fs.ModeSymlink == 0 {
		return os.Link(src, dst)
	}
	target, err := os.Readlink(src)
	if err != nil {
		return err
	}
	return os.Symlink(target, dst)
}

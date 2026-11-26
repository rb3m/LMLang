package main

import (
	"encoding/hex"
	"slices"
	"unicode/utf8"
)

type hidEvent struct {
	at     int64
	device string
	kind   string
	report hidReport
}

type hidTrace struct {
	devices [][]Value
	events  []hidEvent
}

func hidJSON(value Value, tag string) (Value, bool) {
	v, ok := value.(*Variant)
	if !ok || v.C != jsonCtors["json."+tag] {
		return nil, false
	}
	return v.Args[0], true
}

func hidObject(value Value) (*node, bool) {
	obj, ok := hidJSON(value, "JObj")
	if !ok {
		return nil, false
	}
	return obj.(*Coll).Root, true
}

func hidField(obj *node, key, tag string) (Value, bool) {
	item := find(obj, key)
	if item == nil {
		return nil, false
	}
	return hidJSON(item.V, tag)
}

func hidDeviceInfo(value Value) ([]Value, bool) {
	obj, ok := hidObject(value)
	if !ok || size(obj) != len(hidInfoType.Fields) {
		return nil, false
	}
	row := make([]Value, len(hidInfoType.Fields))
	for i, field := range hidInfoType.Fields {
		tag := "JInt"
		if i == 0 || i >= 6 {
			tag = "JStr"
		}
		cell, ok := hidField(obj, field, tag)
		if !ok {
			return nil, false
		}
		row[i] = cell
	}
	return row, row[0] != ""
}

func hidTraceReport(obj *node, key string) (hidReport, bool) {
	id, hasID := hidField(obj, key, "JInt")
	text, hasText := hidField(obj, "data", "JStr")
	if !hasID || !hasText || !hidReportID(id.(int64)) {
		return hidReport{}, false
	}
	raw := text.(string)
	if len(raw)%2 != 0 || !hidLength(int64(len(raw)/2)) {
		return hidReport{}, false
	}
	data, err := hex.DecodeString(raw)
	return hidReport{id.(int64), Bytes(data)}, err == nil
}

func hidTraceEvent(value Value, devices map[string]bool) (hidEvent, bool) {
	obj, ok := hidObject(value)
	if !ok {
		return hidEvent{}, false
	}
	at, hasTime := hidField(obj, "at-ms", "JInt")
	dev, hasDevice := hidField(obj, "dev", "JStr")
	if !hasTime || !hasDevice || at.(int64) < 0 || !devices[dev.(string)] {
		return hidEvent{}, false
	}
	event := hidEvent{at: at.(int64), device: dev.(string)}
	if size(obj) == 3 {
		unplug, ok := hidField(obj, "unplug", "JBool")
		event.kind = "unplug"
		return event, ok && unplug == true
	}
	if size(obj) != 4 {
		return hidEvent{}, false
	}
	for _, kind := range []string{"report-id", "feature-id"} {
		report, ok := hidTraceReport(obj, kind)
		if ok {
			event.kind, event.report = kind, report
			return event, true
		}
	}
	return hidEvent{}, false
}

func parseHidTrace(raw []byte) (hidTrace, bool) {
	if !utf8.Valid(raw) {
		return hidTrace{}, false
	}
	kind, value, _, _ := outcome(func() Value { return prim_json_parse(string(raw)) })
	if kind != "ok" {
		return hidTrace{}, false
	}
	obj, ok := hidObject(value)
	if !ok || size(obj) != 2 {
		return hidTrace{}, false
	}
	devices, hasDevices := hidField(obj, "devices", "JArr")
	events, hasEvents := hidField(obj, "events", "JArr")
	if !hasDevices || !hasEvents {
		return hidTrace{}, false
	}
	trace := hidTrace{}
	ids := map[string]bool{}
	for _, value := range devices.([]Value) {
		row, ok := hidDeviceInfo(value)
		if !ok || ids[row[0].(string)] {
			return hidTrace{}, false
		}
		ids[row[0].(string)] = true
		trace.devices = append(trace.devices, row)
	}
	for _, value := range events.([]Value) {
		event, ok := hidTraceEvent(value, ids)
		if !ok {
			return hidTrace{}, false
		}
		trace.events = append(trace.events, event)
	}
	slices.SortStableFunc(trace.events, func(a, b hidEvent) int {
		if a.at < b.at {
			return -1
		}
		if a.at > b.at {
			return 1
		}
		return 0
	})
	return trace, true
}

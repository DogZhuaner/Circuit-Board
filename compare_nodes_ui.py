#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext


# 标准答案：只比较每条记录 nodes 中的两个触点名称。
# 同一触点对内部顺序不影响匹配，例如 ["A", "B"] 与 ["B", "A"] 视为同一对。
STANDARD_PAIRS: list[tuple[str, str]] = [
    ("QS1-2", "FU1-1"),
    ("FU1-1", "FU2-1"),
    ("QS1-4", "FU1-3"),
    ("QS1-6", "FU1-5"),
    ("FU1-2", "KM2-5/L3"),
    ("KM1-1/L1", "KM2-5/L3"),
    ("FU1-4", "KM2-3/L2"),
    ("KM2-3/L2", "KM1-3/L2"),
    ("FU1-6", "KM2-1/L1"),
    ("KM2-1/L1", "KM1-5/L3"),
    ("KM1-2/T1", "KM2-2/T1"),
    ("KM2-2/T1", "FR1-1/L1"),
    ("KM1-4/T2", "KM2-4/T2"),
    ("KM2-4/T2", "FR1-3/L2"),
    ("KM1-6/T3", "KM2-6/T3"),
    ("KM2-6/T3", "FR1-5/L3"),
    ("FR1-2/T1", "XT1-1"),
    ("FR1-4/T2", "XT1-2"),
    ("FR1-6/T3", "XT1-3"),
    ("FU2-2", "FR1-95/NC"),
    ("FR1-96/NC", "SB3-1/NC"),
    ("SB3-2/NC", "SB2-3/NO"),
    ("SB2-3/NO", "SB1-3/NO"),
    ("SB1-3/NO", "KM2-13/NO"),
    ("KM2-13/NO", "KM1-13/NO"),
    ("SB2-4/NO", "KM2-61/NC"),
    ("KM2-61/NC", "KM1-14/NO"),
    ("KM2-62/NC", "KM1-A1"),
    ("SB1-4/NO", "KM1-61/NC"),
    ("KM1-61/NC", "KM2-14/NO"),
    ("KM1-62/NC", "KM2-A1"),
    ("QS1-8", "KM1-A2"),
    ("KM1-A2", "KM2-A2"),
]

MAX_SCORE = 10
Pair = tuple[str, str]


def normalize_pair(pair: Sequence[Any]) -> Pair:
    if len(pair) != 2:
        raise ValueError(f"触点对长度不是2：{pair!r}")

    a = str(pair[0]).strip()
    b = str(pair[1]).strip()
    if not a or not b:
        raise ValueError(f"触点名称不能为空：{pair!r}")

    return tuple(sorted((a, b)))


def format_pair(pair: Pair) -> str:
    return f"{pair[0]} <-> {pair[1]}"


def load_json_file(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def _is_pair_like(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 2


def _extract_from_items(items: Iterable[Any], source: str) -> tuple[list[Pair], list[str]]:
    pairs: list[Pair] = []
    errors: list[str] = []

    for index, item in enumerate(items, start=1):
        try:
            if isinstance(item, dict) and "nodes" in item:
                pairs.append(normalize_pair(item["nodes"]))
            elif _is_pair_like(item):
                pairs.append(normalize_pair(item))
            else:
                errors.append(f"{source} 第 {index} 项没有可识别的 nodes 触点对")
        except Exception as exc:
            errors.append(f"{source} 第 {index} 项无效：{exc}")

    return pairs, errors


def extract_node_pairs(data: Any) -> tuple[list[Pair], list[str]]:
    """
    优先读取标准规则结构：list[{"nodes": ["触点1", "触点2"], ...}]。
    也兼容少量常见包裹结构，方便直接评测不同程序导出的 JSON。
    """
    if isinstance(data, list):
        return _extract_from_items(data, "顶层列表")

    if not isinstance(data, dict):
        return [], [f"JSON 顶层必须是列表或对象，当前是 {type(data).__name__}"]

    if "nodes" in data:
        nodes = data["nodes"]
        if _is_pair_like(nodes) and not isinstance(nodes[0], (dict, list, tuple)):
            try:
                return [normalize_pair(nodes)], []
            except Exception as exc:
                return [], [f"顶层 nodes 无效：{exc}"]
        if isinstance(nodes, list):
            return _extract_from_items(nodes, "nodes")

    for key in ("data", "items", "rules", "connections"):
        value = data.get(key)
        if isinstance(value, list):
            return _extract_from_items(value, key)

    if isinstance(data.get("pairs"), list):
        return _extract_from_items(data["pairs"], "pairs")

    by_name = data.get("by_name")
    if isinstance(by_name, dict) and isinstance(by_name.get("pairs"), list):
        return _extract_from_items(by_name["pairs"], "by_name.pairs")

    return [], ["未找到可识别的触点对；请确认 JSON 中存在 nodes 字段"]


def counter_to_sorted_list(counter: Counter[Pair]) -> list[Pair]:
    result: list[Pair] = []
    for pair in sorted(counter, key=lambda item: (item[0], item[1])):
        result.extend([pair] * counter[pair])
    return result


def compare_pairs(input_pairs: list[Pair], invalid_count: int = 0) -> dict[str, Any]:
    standard_counter = Counter(normalize_pair(pair) for pair in STANDARD_PAIRS)
    input_counter = Counter(input_pairs)

    matched_counter = standard_counter & input_counter
    missing_counter = standard_counter - input_counter
    extra_counter = input_counter - standard_counter

    missing_count = sum(missing_counter.values())
    extra_count = sum(extra_counter.values())

    # 一个错对通常表现为“多出一对 + 少一对”。按错一对扣1分处理，避免重复扣分。
    wrong_count = min(extra_count, missing_count)
    extra_only_count = max(0, extra_count - wrong_count)
    missing_only_count = max(0, missing_count - wrong_count)
    penalty = wrong_count + extra_only_count + missing_only_count + invalid_count
    score = max(0, MAX_SCORE - penalty)

    return {
        "score": score,
        "penalty": penalty,
        "matched_count": sum(matched_counter.values()),
        "standard_count": sum(standard_counter.values()),
        "input_count": len(input_pairs),
        "invalid_count": invalid_count,
        "wrong_count": wrong_count,
        "extra_only_count": extra_only_count,
        "missing_only_count": missing_only_count,
        "extra_pairs": counter_to_sorted_list(extra_counter),
        "missing_pairs": counter_to_sorted_list(missing_counter),
        "matched_pairs": counter_to_sorted_list(matched_counter),
    }


def build_report(path: str | Path) -> str:
    data = load_json_file(path)
    pairs, errors = extract_node_pairs(data)
    result = compare_pairs(pairs, invalid_count=len(errors))

    lines = [
        f"文件：{Path(path)}",
        f"最终匹配分数：{result['score']} / {MAX_SCORE}",
        "",
        f"标准触点对数量：{result['standard_count']}",
        f"输入有效触点对数量：{result['input_count']}",
        f"完全匹配触点对数量：{result['matched_count']}",
        "",
        "扣分统计：",
        f"  错对：{result['wrong_count']} 对",
        f"  多对：{result['extra_only_count']} 对",
        f"  少对：{result['missing_only_count']} 对",
        f"  无效记录：{result['invalid_count']} 条",
        f"  总扣分：{result['penalty']} 分",
    ]

    if result["extra_pairs"]:
        lines.extend(["", "输入中多出或错误的触点对："])
        lines.extend(f"  - {format_pair(pair)}" for pair in result["extra_pairs"])

    if result["missing_pairs"]:
        lines.extend(["", "标准中缺失的触点对："])
        lines.extend(f"  - {format_pair(pair)}" for pair in result["missing_pairs"])

    if errors:
        lines.extend(["", "无效记录详情："])
        lines.extend(f"  - {error}" for error in errors)

    if not result["extra_pairs"] and not result["missing_pairs"] and not errors:
        lines.extend(["", "比对结果：触点对完全吻合。"])

    return "\n".join(lines)


class CompareApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("触点对 JSON 比对")
        self.geometry("900x650")
        self.minsize(760, 520)

        self.selected_path = tk.StringVar(value="")
        self.score_text = tk.StringVar(value=f"分数：-- / {MAX_SCORE}")
        self.status_text = tk.StringVar(value=f"标准答案共 {len(STANDARD_PAIRS)} 对触点。请选择输入 JSON 文件。")

        self._build_ui()

    def _build_ui(self) -> None:
        root = tk.Frame(self, padx=16, pady=16)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        title = tk.Label(
            root,
            text="触点对 JSON 比对",
            anchor="w",
            font=("Arial", 20, "bold"),
        )
        title.grid(row=0, column=0, sticky="ew")

        subtitle = tk.Label(
            root,
            text="只比较 nodes 中的两个触点名称；触点对内部顺序和触点对先后顺序都不影响匹配。",
            anchor="w",
            font=("Arial", 12),
        )
        subtitle.grid(row=1, column=0, sticky="ew", pady=(4, 14))

        file_row = tk.Frame(root)
        file_row.grid(row=2, column=0, sticky="ew")
        file_row.columnconfigure(1, weight=1)

        tk.Label(file_row, text="输入文件：", font=("Arial", 12)).grid(row=0, column=0, sticky="w")
        path_entry = tk.Entry(file_row, textvariable=self.selected_path, font=("Arial", 12))
        path_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8), ipady=5)

        tk.Button(file_row, text="选择输入 JSON", command=self.choose_file, width=16).grid(row=0, column=2, padx=(0, 8))
        tk.Button(file_row, text="开始比对", command=self.compare_selected, width=12).grid(row=0, column=3, padx=(0, 8))
        tk.Button(file_row, text="清空结果", command=self.clear_result, width=10).grid(row=0, column=4)

        score_row = tk.Frame(root, highlightthickness=1, highlightbackground="#d1d5db", padx=12, pady=10)
        score_row.grid(row=3, column=0, sticky="ew", pady=(14, 12))
        score_row.columnconfigure(0, weight=1)

        tk.Label(score_row, textvariable=self.score_text, anchor="w", font=("Arial", 22, "bold")).grid(row=0, column=0, sticky="ew")
        tk.Label(
            score_row,
            text="满分 10；多对、少对、错对各扣 1 分，最低 0 分。",
            anchor="e",
            font=("Arial", 12),
        ).grid(row=0, column=1, sticky="e")
        tk.Label(score_row, textvariable=self.status_text, anchor="w", font=("Arial", 12)).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )

        self.output = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Menlo", 12))
        self.output.grid(row=4, column=0, sticky="nsew")
        self._set_output(
            "操作步骤：\n"
            "1. 点击“选择输入 JSON”选择需要比对的文件。\n"
            "2. 选择后会自动比对，也可以点击“开始比对”。\n"
            "3. 比对完成后，这里会显示最终匹配分数以及多对、少对、错对明细。"
        )

        bottom_row = tk.Frame(root)
        bottom_row.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        tk.Button(bottom_row, text="退出", command=self.destroy, width=10).pack(side=tk.RIGHT)

    def _set_output(self, text: str) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, text)
        self.output.configure(state=tk.DISABLED)

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择输入 JSON 文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.selected_path.set(path)
        self.compare_selected()

    def compare_selected(self) -> None:
        path = self.selected_path.get().strip()
        if not path:
            messagebox.showinfo("提示", "请先选择一个 JSON 文件。")
            return

        try:
            report = build_report(path)
        except Exception as exc:
            self.score_text.set(f"分数：-- / {MAX_SCORE}")
            self.status_text.set("比对失败，请检查 JSON 文件格式。")
            self._set_output(f"比对失败：{exc}")
            messagebox.showerror("比对失败", str(exc))
            return

        score_line = next((line for line in report.splitlines() if line.startswith("最终匹配分数：")), "")
        if score_line:
            self.score_text.set(score_line.replace("最终匹配分数", "分数"))
        self.status_text.set("比对完成。")
        self._set_output(report)

    def clear_result(self) -> None:
        self.selected_path.set("")
        self.score_text.set(f"分数：-- / {MAX_SCORE}")
        self.status_text.set(f"标准答案共 {len(STANDARD_PAIRS)} 对触点。请选择输入 JSON 文件。")
        self._set_output(
            "操作步骤：\n"
            "1. 点击“选择输入 JSON”选择需要比对的文件。\n"
            "2. 选择后会自动比对，也可以点击“开始比对”。\n"
            "3. 比对完成后，这里会显示最终匹配分数以及多对、少对、错对明细。"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="比对 JSON 中 nodes 触点对是否与标准答案一致。")
    parser.add_argument("json_path", nargs="?", help="可选：直接在命令行比对指定 JSON 文件")
    args = parser.parse_args()

    if args.json_path:
        print(build_report(args.json_path))
        return

    app = CompareApp()
    app.mainloop()


if __name__ == "__main__":
    main()

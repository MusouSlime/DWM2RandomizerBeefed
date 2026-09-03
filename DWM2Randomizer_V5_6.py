from __future__ import annotations

import hashlib
import json
import random
import secrets
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "DWM2 Randomizer"
VERSION = "5.6.0-gui-alpha"

MONSTER_TABLE = 0xD4368
MONSTER_RECORD_SIZE = 47
MONSTER_COUNT = 313
ENCOUNTER_TABLE = 0xD008F
ENCOUNTER_RECORD_SIZE = 26
ENCOUNTER_COUNT = 614
MIN_ROM_SIZE = max(
    MONSTER_TABLE + MONSTER_RECORD_SIZE * MONSTER_COUNT,
    ENCOUNTER_TABLE + ENCOUNTER_RECORD_SIZE * ENCOUNTER_COUNT,
)

VALID_RANGES = (
    (0x01, 0x1A), (0x24, 0x42), (0x47, 0x66), (0x6A, 0x84),
    (0x8D, 0xA7), (0xB0, 0xC9), (0xD3, 0xF0), (0xF6, 0x110),
    (0x119, 0x138), (0x13C, 0x15B), (0x15F, 0x174),
)
VALID_MONSTERS = tuple(
    monster_id
    for low, high in VALID_RANGES
    for monster_id in range(low, high + 1)
)

TIER_ONE_SKILLS = (
    1,4,7,10,13,16,19,21,22,25,27,30,32,33,34,35,36,37,39,41,
    43,45,46,47,49,51,52,53,54,56,57,58,60,61,62,63,64,68,72,
    74,75,76,78,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,
    95,96,97,98,99,101,102,103,104,105,106,107,108,109,110,111,
    112,113,114,115,116,117,118,120,121,122,123,124,125,126,127,
    128,129,130,131,132,133,137,138,139,141,143,144,145,146,147,
    148,149,150,151,153,155,156,157,158,159,160,161,162,163,164,
    165,166,167,168,169,
)

BOSS_ENCOUNTERS = {
    6,25,27,49,67,99,106,107,108,114,115,116,130,131,132,133,134,
    135,376,385,398,399,408,409,410,411,421,426,
}


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def seeded_rng(seed: str) -> random.Random:
    number = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:8], "big")
    return random.Random(number)


def rom_title(data: bytes) -> str:
    if len(data) < 0x150:
        return ""
    return data[0x134:0x144].rstrip(b"\x00 ").decode("ascii", "replace")


def edition_hint(data: bytes, filename: str) -> str:
    text = f"{rom_title(data)} {Path(filename).stem}".upper()
    if "TARA" in text or "DWM2TA" in text:
        return "Tara's Adventure"
    if "COBI" in text or "DWM2CJ" in text:
        return "Cobi's Journey"
    return "Unknown DWM2 edition"


def validate_rom(data: bytes) -> None:
    if len(data) < 0x150:
        raise ValueError("The selected file is too small to be a Game Boy Color ROM.")
    if data[0x104:0x108] != bytes.fromhex("CEED6666"):
        raise ValueError("The selected file does not contain a valid Game Boy header logo.")
    if len(data) < MIN_ROM_SIZE:
        raise ValueError(
            f"The ROM is too small for the DWM2 tables. Required: {MIN_ROM_SIZE:#x}; "
            f"found: {len(data):#x}."
        )


def repair_checksums(rom: bytearray) -> None:
    checksum = 0
    for value in rom[0x134:0x14D]:
        checksum = (checksum - value - 1) & 0xFF
    rom[0x14D] = checksum
    total = (sum(rom[:0x14E]) + sum(rom[0x150:])) & 0xFFFF
    rom[0x14E] = total >> 8
    rom[0x14F] = total & 0xFF


def redistribute(rng: random.Random, original: bytes, low: int, high: int) -> bytes:
    total = sum(max(low, min(high, value)) for value in original)
    result = [low] * len(original)
    remaining = min(total - low * len(result), (high - low) * len(result))
    available = list(range(len(result)))
    while remaining > 0 and available:
        slot = rng.choice(available)
        result[slot] += 1
        remaining -= 1
        if result[slot] >= high:
            available.remove(slot)
    return bytes(result)


def scale_u16(rom: bytearray, offset: int, percent: int, maximum: int = 65535) -> None:
    value = int.from_bytes(rom[offset:offset + 2], "little")
    value = max(0, min(maximum, round(value * percent / 100)))
    rom[offset:offset + 2] = value.to_bytes(2, "little")


@dataclass
class Summary:
    growth_records: int = 0
    resistance_records: int = 0
    skill_records: int = 0
    encounter_records: int = 0
    scaled_records: int = 0
    genius_records: int = 0


def randomize_rom(data: bytes, seed: str, options: dict) -> tuple[bytes, Summary]:
    validate_rom(data)
    rom = bytearray(data)
    rng = seeded_rng(seed)
    summary = Summary()

    for index in range(MONSTER_COUNT):
        base = MONSTER_TABLE + index * MONSTER_RECORD_SIZE

        if options["growth"]:
            rom[base + 14:base + 20] = redistribute(rng, rom[base + 14:base + 20], 1, 31)
            summary.growth_records += 1

        if options["resistances"]:
            rom[base + 20:base + 47] = redistribute(rng, rom[base + 20:base + 47], 0, 3)
            summary.resistance_records += 1

        if options["skills"]:
            rom[base + 10:base + 13] = bytes(rng.sample(TIER_ONE_SKILLS, 3))
            summary.skill_records += 1

        if options["genius"]:
            rom[base + 19] = 31
            summary.genius_records += 1

    for index in range(ENCOUNTER_COUNT):
        base = ENCOUNTER_TABLE + index * ENCOUNTER_RECORD_SIZE

        if options["encounters"]:
            current_id = int.from_bytes(rom[base:base + 2], "little")
            if current_id not in (0x5A, 0xB9):
                if index == 0 and options["starter_id"]:
                    monster_id = options["starter_id"]
                elif index == 26:
                    monster_id = rng.randrange(0x13C, 0x15C)
                else:
                    monster_id = rng.choice(VALID_MONSTERS)
                rom[base:base + 2] = monster_id.to_bytes(2, "little")
                summary.encounter_records += 1

        scale_u16(rom, base + 6, options["exp_percent"])
        stat_percent = options["boss_percent"] if index in BOSS_ENCOUNTERS else options["stat_percent"]
        for stat in range(6):
            scale_u16(rom, base + 10 + stat * 2, stat_percent, 999)

        if options["genius"]:
            rom[base + 20:base + 22] = (999).to_bytes(2, "little")

        summary.scaled_records += 1

    repair_checksums(rom)
    return bytes(rom), summary


class RandomizerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.geometry("900x760")
        self.minsize(760, 650)

        self.rom_data: bytes | None = None
        self.rom_path = tk.StringVar()
        self.seed = tk.StringVar()
        self.status = tk.StringVar(value="Select a clean DWM2 ROM to begin.")

        self.opt_growth = tk.BooleanVar(value=True)
        self.opt_resistances = tk.BooleanVar(value=True)
        self.opt_skills = tk.BooleanVar(value=True)
        self.opt_encounters = tk.BooleanVar(value=True)
        self.opt_genius = tk.BooleanVar(value=False)
        self.starter_id = tk.StringVar(value="0")
        self.exp_percent = tk.IntVar(value=100)
        self.stat_percent = tk.IntVar(value=100)
        self.boss_percent = tk.IntVar(value=100)

        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Dragon Warrior Monsters 2 Randomizer",
                  font=("TkDefaultFont", 19, "bold")).pack(anchor="w")
        ttk.Label(outer, text=f"Standalone Linux and Windows GUI build, version {VERSION}").pack(anchor="w", pady=(2, 12))

        self._file_row(outer)
        self._seed_row(outer)
        ttk.Label(outer, textvariable=self.status, wraplength=840).pack(anchor="w", pady=(5, 10))

        options = ttk.LabelFrame(outer, text="Randomization Options", padding=10)
        options.pack(fill="x", pady=5)
        for label, variable in (
            ("Redistribute monster growth", self.opt_growth),
            ("Redistribute monster resistances", self.opt_resistances),
            ("Randomize monster skills", self.opt_skills),
            ("Randomize encounters", self.opt_encounters),
            ("Genius Mode", self.opt_genius),
        ):
            ttk.Checkbutton(options, text=label, variable=variable).pack(anchor="w")

        starter = ttk.Frame(options)
        starter.pack(fill="x", pady=(6, 0))
        ttk.Label(starter, text="Starting monster ID", width=25).pack(side="left")
        ttk.Entry(starter, textvariable=self.starter_id, width=12).pack(side="left")
        ttk.Label(starter, text="Use 0 for a random starter. Hex such as 0x56 is accepted.").pack(side="left", padx=8)

        scaling = ttk.LabelFrame(outer, text="Scaling", padding=10)
        scaling.pack(fill="x", pady=5)
        self._scale_row(scaling, "Enemy EXP", self.exp_percent)
        self._scale_row(scaling, "Wild enemy stats", self.stat_percent)
        self._scale_row(scaling, "Boss stats", self.boss_percent)

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=10)
        ttk.Button(buttons, text="Generate Randomized ROM", command=self.generate).pack(side="left")
        ttk.Button(buttons, text="Clear Log", command=self.clear_log).pack(side="left", padx=8)

        self.log = tk.Text(outer, height=14, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)

    def _file_row(self, parent) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Input ROM", width=18).pack(side="left")
        ttk.Entry(row, textvariable=self.rom_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", command=self.pick_rom).pack(side="left", padx=(8, 0))

    def _seed_row(self, parent) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Seed", width=18).pack(side="left")
        ttk.Entry(row, textvariable=self.seed).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Random Seed", command=self.new_seed).pack(side="left", padx=(8, 0))

    def _scale_row(self, parent, label, variable) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=25).pack(side="left")
        ttk.Scale(row, from_=0, to=500, variable=variable).pack(side="left", fill="x", expand=True)
        ttk.Spinbox(row, from_=0, to=500, textvariable=variable, width=7).pack(side="left", padx=(8, 0))
        ttk.Label(row, text="%").pack(side="left")

    def new_seed(self) -> None:
        self.seed.set(str(secrets.randbits(64)))

    def write_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def pick_rom(self) -> None:
        path = filedialog.askopenfilename(
            title="Select DWM2 ROM",
            filetypes=[("Game Boy Color ROM", "*.gbc"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
            validate_rom(data)
            self.rom_path.set(path)
            self.rom_data = data
            edition = edition_hint(data, path)
            self.status.set(
                f"Detected: {edition} | Header: {rom_title(data)!r} | "
                f"Size: {len(data):,} bytes | MD5: {md5(data)}"
            )
            self.write_log(f"Loaded {Path(path).name} as {edition}.")
        except Exception as exc:
            self.rom_data = None
            self.status.set("ROM validation failed.")
            messagebox.showerror(APP_NAME, str(exc))

    def generate(self) -> None:
        try:
            if self.rom_data is None:
                self.pick_rom()
            if self.rom_data is None:
                return

            raw_starter = self.starter_id.get().strip() or "0"
            starter = int(raw_starter, 0)
            if starter != 0 and starter not in VALID_MONSTERS:
                raise ValueError("The starter ID is outside the supported DWM2 monster ranges.")

            seed = self.seed.get().strip()
            if not seed:
                self.new_seed()
                seed = self.seed.get()

            options = {
                "growth": self.opt_growth.get(),
                "resistances": self.opt_resistances.get(),
                "skills": self.opt_skills.get(),
                "encounters": self.opt_encounters.get(),
                "genius": self.opt_genius.get(),
                "starter_id": starter,
                "exp_percent": int(self.exp_percent.get()),
                "stat_percent": int(self.stat_percent.get()),
                "boss_percent": int(self.boss_percent.get()),
            }

            output, summary = randomize_rom(self.rom_data, seed, options)
            default_name = f"DWM2_Randomized_{seed}.gbc"
            target = filedialog.asksaveasfilename(
                title="Save Randomized ROM",
                defaultextension=".gbc",
                initialfile=default_name,
                filetypes=[("Game Boy Color ROM", "*.gbc")],
            )
            if not target:
                return

            Path(target).write_bytes(output)
            manifest = {
                "application": APP_NAME,
                "version": VERSION,
                "seed": seed,
                "edition_hint": edition_hint(self.rom_data, self.rom_path.get()),
                "input_md5": md5(self.rom_data),
                "input_sha256": sha256(self.rom_data),
                "output_sha256": sha256(output),
                "options": options,
                "summary": asdict(summary),
            }
            manifest_path = target + ".json"
            Path(manifest_path).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            self.write_log(f"Created: {target}")
            self.write_log(f"Manifest: {manifest_path}")
            self.write_log(f"Seed: {seed}")
            self.write_log(json.dumps(asdict(summary), indent=2))
            messagebox.showinfo(APP_NAME, "Randomized ROM and JSON manifest created successfully.")
        except Exception as exc:
            self.write_log("ERROR: " + str(exc))
            messagebox.showerror(APP_NAME, str(exc))


if __name__ == "__main__":
    try:
        RandomizerApp().mainloop()
    except Exception:
        Path("DWM2Randomizer_crash.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise

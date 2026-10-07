/**
 * A stand-in for the core's services (services.py), in memory, for the
 * playground's app window. Same method names, same shapes, same refusals:
 * if a view works here against this, it speaks the core's language.
 */

import { ServiceError, type Services } from "./hub";

const minutesAgo = (n: number) => new Date(Date.now() - n * 60_000).toISOString();

const FIELDS = [
  {
    tab: "Apparence",
    section: "appearance",
    key: "scale",
    label: "Taille",
    kind: "float",
    minimum: 0.5,
    maximum: 4,
    step: 0.25,
    value: 1,
  },
  {
    tab: "Apparence",
    section: "appearance",
    key: "opacity",
    label: "Opacité",
    kind: "float",
    minimum: 0.2,
    maximum: 1,
    step: 0.05,
    value: 1,
  },
  {
    tab: "Apparence",
    section: "appearance",
    key: "click_through_when_idle",
    label: "Laisser les clics traverser le sorcier",
    kind: "bool",
    hint: "Utile s'il est posé sur un bouton que vous utilisez souvent.",
    value: false,
  },
  {
    tab: "Raccourcis",
    section: "hotkeys",
    key: "ask_claude",
    label: "Demander à Claude",
    kind: "hotkey",
    value: "ctrl+alt+C",
  },
  {
    tab: "Raccourcis",
    section: "hotkeys",
    key: "quick_note",
    label: "Note rapide",
    kind: "hotkey",
    value: "ctrl+alt+N",
  },
  {
    tab: "Raccourcis",
    section: "hotkeys",
    key: "clipboard",
    label: "Presse-papiers",
    kind: "hotkey",
    value: "ctrl+alt+V",
  },
  {
    tab: "Claude",
    section: "claude",
    key: "enabled",
    label: "Activer Claude",
    kind: "bool",
    value: true,
  },
  {
    tab: "Claude",
    section: "claude",
    key: "permission_timeout_seconds",
    label: "Délai d'autorisation",
    kind: "int",
    minimum: 5,
    maximum: 600,
    step: 1,
    suffix: " s",
    hint: "Passé ce délai sans réponse, l'action est refusée. Le silence ne vaut pas accord.",
    value: 110,
  },
  {
    tab: "Système",
    section: "clipboard",
    key: "enabled",
    label: "Enregistrer l'historique du presse-papiers",
    kind: "bool",
    value: true,
  },
];

const DIFF = `--- settings.json
+++ settings.json
@@ -1,3 +1,12 @@
 {
-  "theme": "dark"
+  "theme": "dark",
+  "hooks": {
+    "PreToolUse": [
+      { "hooks": [{ "type": "command", "command": "pythonw.exe" }] }
+    ]
+  }
 }`;

/** A fresh set of services, with a little data in each. */
export function fakeServices(): Services {
  const values = new Map(
    FIELDS.map((f) => [`${f.section}.${f.key}`, f.value as unknown]),
  );
  let memory = "";
  let nextId = 10;
  const clips = [
    {
      id: 1,
      body: "npm run tauri dev",
      created_at: minutesAgo(2),
      kind: "text",
      thumbnail: null,
    },
    {
      id: 2,
      body: "https://v2.tauri.app/plugin/dialog/",
      created_at: minutesAgo(50),
      kind: "text",
      thumbnail: null,
    },
    {
      id: 3,
      body: "Image 640×320",
      created_at: minutesAgo(200),
      kind: "image",
      thumbnail: null,
    },
  ];
  const notes = [
    {
      id: 4,
      body: "Acheter du pain",
      created_at: minutesAgo(30),
      kind: "text",
      thumbnail: null,
    },
  ];
  const timers = [{ id: 5, label: "Thé", remaining: 240, total: 300 }];
  const conversations = [
    {
      id: 6,
      kind: "question",
      kind_label: "Question",
      title: "Pourquoi le ciel est bleu",
      updated_at: minutesAgo(5),
      pinned: false,
      project: "",
      resumable: true,
    },
    {
      id: 7,
      kind: "agent",
      kind_label: "Agent",
      title: "Faire passer les tests",
      updated_at: minutesAgo(60 * 30),
      pinned: true,
      project: "desktop-avatar",
      resumable: false,
    },
  ];
  let installed = false;
  let autostart = false;

  const find = <T extends { id: number }>(list: T[], id: unknown, what: string) => {
    const item = list.find((i) => i.id === id);
    if (!item) throw new ServiceError("not_found", `${what} n'existe plus.`);
    return item;
  };
  const filter = <T extends { body: string }>(list: T[], search: unknown) =>
    list.filter(
      (i) => !search || i.body.toLowerCase().includes(String(search).toLowerCase()),
    );
  const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

  return (method, params) => {
    switch (method) {
      case "settings.read":
        return {
          fields: FIELDS.map((f) => ({
            ...f,
            value: values.get(`${f.section}.${f.key}`),
          })),
          memory: {
            text: memory || "# Moi\n",
            from_file: !!memory,
            template: "# Moi\n",
            limit: 6000,
          },
        };
      case "settings.memory_size":
        return {
          sent: String(params.text).length,
          truncated: String(params.text).length > 6000,
        };
      case "settings.check_hotkeys": {
        const bindings = params.bindings as Record<string, string>;
        const seen = new Map<string, string>();
        const problems: string[] = [];
        for (const [action, spec] of Object.entries(bindings)) {
          if (!spec) continue;
          const other = seen.get(spec.toLowerCase());
          if (other)
            problems.push(`« ${other} » et « ${action} » utilisent tous deux ${spec}.`);
          seen.set(spec.toLowerCase(), action);
        }
        return { problems };
      }
      case "settings.write": {
        for (const [name, value] of Object.entries(params.values as object)) {
          const f = FIELDS.find((x) => `${x.section}.${x.key}` === name);
          if (!f) throw new ServiceError("invalid", `Réglage inconnu : ${name}`);
          if (
            f.minimum !== undefined &&
            ((value as number) < f.minimum || (value as number) > f.maximum!)
          ) {
            throw new ServiceError(
              "invalid",
              `« ${f.label} » doit être entre ${f.minimum} et ${f.maximum}.`,
            );
          }
          values.set(name, value);
        }
        if (typeof params.memory === "string") memory = params.memory;
        return { written: Object.keys(params.values as object).length };
      }
      case "system.info":
        return { autostart, hooks_installed: installed, hooks_stale: false };
      case "system.autostart":
        autostart = !!params.enabled;
        return { autostart };
      case "system.open_config":
        return {};
      case "clips.list":
        return { items: filter(clips, params.search) };
      case "notes.list":
        return { items: filter(notes, params.search) };
      case "clips.copy":
        return { copied: find(clips, params.id, "Cette entrée").kind };
      case "notes.copy":
        find(notes, params.id, "Cette note");
        return {};
      case "clips.delete":
        clips.splice(clips.indexOf(find(clips, params.id, "Cette entrée")), 1);
        return {};
      case "notes.delete":
        notes.splice(notes.indexOf(find(notes, params.id, "Cette note")), 1);
        return {};
      case "notes.add": {
        const body = String(params.body).trim();
        if (!body)
          throw new ServiceError("invalid", "Impossible d'enregistrer une note vide.");
        notes.unshift({
          id: ++nextId,
          body,
          created_at: new Date().toISOString(),
          kind: "text",
          thumbnail: null,
        });
        return { id: nextId };
      }
      case "timers.list":
        return {
          items: timers.map((t) => ({ ...t, remaining_text: clock(t.remaining) })),
        };
      case "timers.add": {
        const text = String(params.duration ?? "");
        const seconds =
          params.seconds !== undefined
            ? Number(params.seconds)
            : /^\d+$/.test(text)
              ? Number(text) * 60
              : NaN;
        if (Number.isNaN(seconds)) {
          throw new ServiceError(
            "invalid",
            "Durée non reconnue. Essayez par exemple 25, 25m, 1h30 ou 90s.",
          );
        }
        const label = String(params.label || "Rappel");
        timers.push({ id: ++nextId, label, remaining: seconds, total: seconds });
        return { id: nextId, label };
      }
      case "timers.cancel":
        timers.splice(timers.indexOf(find(timers, params.id, "Ce rappel")), 1);
        return {};
      case "timers.cancel_all":
        timers.length = 0;
        return {};
      case "launcher.list":
        return { items: [{ index: 0, label: "Bloc-notes", target: "notepad.exe" }] };
      case "launcher.run":
        return {};
      case "history.kinds":
        return {
          kinds: [
            { value: "question", label: "Question" },
            { value: "agent", label: "Agent" },
          ],
        };
      case "history.list": {
        const items = conversations.filter((c) => !params.kind || c.kind === params.kind);
        if (params.search) {
          return {
            mode: "search",
            items: items.map((c) => ({ ...c, snippet: "… le [ciel] …" })),
          };
        }
        return {
          mode: "groups",
          groups: [
            { title: "Épinglées", items: items.filter((c) => c.pinned) },
            { title: "Aujourd'hui", items: items.filter((c) => !c.pinned) },
          ].filter((g) => g.items.length),
        };
      }
      case "history.get": {
        const c = find(conversations, params.id, "Cette discussion");
        return {
          conversation: c,
          markdown: `## ${c.title}\n\n**Vous** : ${c.title} ?\n\n**Claude** : la diffusion de *Rayleigh*.`,
        };
      }
      case "history.rename":
        find(conversations, params.id, "Cette discussion").title = String(params.title);
        return {};
      case "history.pin":
        find(conversations, params.id, "Cette discussion").pinned = !!params.pinned;
        return {};
      case "history.delete":
        conversations.splice(
          conversations.indexOf(find(conversations, params.id, "Cette discussion")),
          1,
        );
        return {};
      case "history.clear": {
        const deleted = conversations.length;
        conversations.length = 0;
        return { deleted };
      }
      case "history.resume":
      case "history.export":
        return {};
      case "transcripts.list":
        return {
          items: [
            {
              session_id: "s1",
              title: "Refactor du supervisor",
              project: "desktop-avatar",
              modified: minutesAgo(90),
            },
          ],
        };
      case "transcripts.get":
        return {
          markdown: "**Vous** : refactorise le supervisor\n\n**Claude** : c'est fait.",
        };
      case "hooks.plan":
        return {
          installing: !!params.install,
          changed: !!params.install !== installed,
          path: "C:\\Users\\vous\\.claude\\settings.json",
          diff: DIFF,
          installed,
          stale: false,
        };
      case "hooks.apply":
        if (params.seen !== DIFF)
          throw new ServiceError(
            "stale",
            "settings.json a changé depuis l'affichage : relisez le changement.",
          );
        installed = !!params.install;
        return { installed };
      case "onboarding.info":
        return {
          checks: [
            {
              label: "Claude Code",
              ok: false,
              detail:
                "Pas connecté. Lancez `claude auth login` dans un terminal, puis revenez.",
              action: "",
            },
            {
              label: "Vos sessions Claude Code",
              ok: installed,
              detail: "Pas encore reliées.",
              action: installed ? "" : "Installer…",
            },
          ],
          shortcuts: [{ label: "Demander à Claude", keys: "Ctrl + Alt + C" }],
        };
      case "onboarding.done":
        return {};
      case "agents.last_folder":
        return { folder: "C:\\Users\\vous\\projets" };
      case "agents.launch":
        if (!String(params.task ?? "").trim())
          throw new ServiceError("invalid", "Décrivez la tâche.");
        if (!String(params.folder ?? "").trim())
          throw new ServiceError("invalid", "Choisissez un dossier qui existe.");
        return {};
      default:
        throw new ServiceError("unknown_method", `Méthode inconnue : ${method}`);
    }
  };
}

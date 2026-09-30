# Little Wizard — character sheet and image brief

Ce document sert à deux choses : garder le personnage **cohérent d'une image à
l'autre**, et vous donner des prompts prêts à coller si vous voulez générer les
images plutôt que de garder le rendu QPainter.

**Vous n'êtes pas obligé de tout faire.** Le chargeur accepte un jeu partiel :
seul `idle` est obligatoire, et toute pose manquante retombe sur `idle`. Vous
pouvez donc en générer une, la regarder dans l'app, et continuer.

---

## Où déposer les fichiers

```
assets/character/wizard_<pose>_<numéro>.png
```

Le dossier `assets/character/` est créé et lu automatiquement. Dès qu'un
`wizard_idle_1.png` valide s'y trouve, l'app bascule sur les images et
n'utilise plus le dessin par code — rien d'autre à configurer.

Pour vérifier :

```powershell
.venv\Scripts\python.exe tools\contact_sheet.py --assets
```

Cela écrit `docs/poses.png` avec toutes les poses à 96, 48, 32 et 16 px, et
affiche `renderer: sheet` si vos images ont bien été prises en compte (et
`renderer: painter` sinon — c'est le signe que le nom d'un fichier ne colle
pas).

---

## Spécifications techniques

| Point | Valeur |
|---|---|
| Format | PNG, **fond transparent** (pas de damier, pas de blanc) |
| Taille | **512 × 512** px, carré |
| Cadrage | **identique sur toutes les images** — voir ci-dessous |
| Numérotation | `_1`, `_2`, … dans l'ordre de l'animation (le zéro-padding est accepté) |
| Nombre de frames | 1 suffit. 4 à 8 pour une vraie animation |

**Le cadrage est le point critique.** Si le personnage change de taille ou de
position d'une pose à l'autre, il sautera à l'écran à chaque changement d'état.
Règle : le personnage occupe **la même boîte dans les 512 px pour toutes les
images** —

- pieds (bas de la robe) sur la ligne **y = 470**
- pointe du chapeau vers **y = 40**
- centre du corps sur **x = 256**
- largeur maximale (chapeau compris) **≈ 300 px**, centrée

Un accessoire qui sort de cette boîte (le bâton levé, le parchemin tendu) a le
droit de déborder, mais **le corps, lui, ne bouge pas**.

---

## Fiche personnage

> Un petit sorcier africain, mignon et attachant. Grosse tête ronde, petit
> corps : proportions de mascotte, environ **un tiers de la hauteur pour la
> tête**. Peau foncée. **Grands yeux ronds très expressifs** avec un reflet
> blanc. Robe longue indigo et chapeau pointu légèrement courbé, tous deux
> ornés de bandes géométriques sobres inspirées du bogolan malien et du kente
> ghanéen (triangles, losanges, lignes — jamais de motif figuratif). Des
> cauris sur le bord du chapeau et en collier. Un bâton de bois sculpté dont
> l'embout s'illumine.
>
> Style : illustration vectorielle propre, aplats et dégradés doux, contours
> nets, pas de texture photographique, pas de rendu 3D, pas de contour noir
> épais de cartoon. L'ensemble doit rester lisible réduit à 48 px.
>
> **Respectueux et valorisant.** C'est un personnage digne et chaleureux, pas
> une caricature : pas de traits exagérés, pas de clichés, pas d'imagerie
> coloniale ou « tribale » générique.

### Palette exacte

| Rôle | Hex |
|---|---|
| Indigo profond (ombres de la robe, chapeau) | `#171B44` |
| Indigo (robe, chapeau) | `#2A3373` |
| Indigo clair (lumière sur la robe) | `#3D4A9B` |
| Ocre (bande du chapeau) | `#D9982F` |
| Terre cuite (bande du bas de la robe) | `#B4543A` |
| Or (motifs, anneaux du bâton) | `#F2C14E` |
| Crème (cauris, blanc des yeux) | `#F6EFE0` |
| Peau | `#7A4B2A` |
| Peau, lumière | `#8E5C36` |
| Peau, ombre | `#5C361D` |
| Encre (pupilles, bouche) | `#191A22` |
| Bois du bâton | `#784E2C` |

### L'embout du bâton = l'indicateur d'état

C'est le seul élément dont **la couleur change selon la pose**. C'est
volontaire : l'état de l'application se lit sur la lumière du bâton, pas sur un
badge collé à côté du personnage. Couleur du cœur lumineux par pose :

| Pose | Cœur | Halo |
|---|---|---|
| `idle` | `#F2C14E` | `#F2C14E` |
| `busy` | `#D9982F` | `#E8A93F` |
| `stressed` | `#F0685A` | `#E2574C` |
| `tired` | `#9C8FD4` | `#7B6BA8` |
| `working` | `#78C0F5` | `#3E93DC` |
| `thinking` | `#8FE0EC` | `#4FC3D6` |
| `waiting_approval` | `#FFC85C` | `#FF9F1C` |
| `success` | `#74E3A8` | `#34C77B` |
| `confused` | `#F0685A` | `#D6453A` |
| `sleeping` | `#5A5F86` | `#3E4368` |
| `greeting` | `#F2C14E` | `#F2C14E` |
| `listening` | `#6FE3CE` | `#2FBFA6` |
| `speaking` | `#9AD7F7` | `#5AB0E8` |
| `pointing` | `#FFD97A` | `#F2B138` |

---

## Le préambule à coller devant chaque prompt

Les générateurs d'images oublient le personnage d'une image à l'autre. Collez
ce bloc **avant** chaque prompt de pose, mot pour mot, pour qu'il reste le même :

> Cute African little wizard mascot, clean flat vector illustration with soft
> gradients, transparent background, centred, full body. Big round head (about
> one third of the total height), small compact body. Dark brown skin
> (#7A4B2A), very large round expressive eyes with a white catchlight. Long
> indigo robe (#2A3373) with a terracotta hem band (#B4543A) and a long
> slightly curved indigo pointed wizard hat with an ochre band (#D9982F), both
> decorated with simple geometric bogolan and kente motifs in gold (#F2C14E) —
> triangles, diamonds and lines only. Cowrie shells on the hat brim and as a
> necklace. He holds a carved wooden staff (#784E2C) with a glowing orb at the
> top. Dignified, warm and friendly, never a caricature. No thick black cartoon
> outline, no 3D render, no photographic texture, no text. Must stay readable
> when scaled down to 48 pixels.

Puis ajoutez la ligne de la pose, et pour chacune : **« the staff orb glows
<couleur> »** en reprenant le tableau ci-dessus.

---

## Les quatorze poses

Colonne « frames » = ce que je recommande si vous voulez une vraie animation.
**Une seule image par pose suffit pour commencer.**

| Fichier | Frames | Boucle | Prompt de pose (à ajouter au préambule) |
|---|---|---|---|
| `wizard_idle_1.png` | 6 | oui | Standing calmly, relaxed, a gentle friendly smile, staff held upright at his side. The staff orb glows warm gold `#F2C14E`. |
| `wizard_busy_1.png` | 4 | oui | Concentrating, mouth a straight determined line, brows lowered, leaning very slightly forward. The staff orb glows ochre `#D9982F`. |
| `wizard_stressed_1.png` | 4 | oui | Worried, wide open mouth, one large sweat drop beside his head, brows raised in the middle. The staff orb glows red `#F0685A`. |
| `wizard_tired_1.png` | 4 | oui | Weary, half-closed eyes, wavy unhappy mouth, shoulders drooping, small floating "z" letters near the hat. The staff orb glows muted violet `#9C8FD4`. |
| `wizard_working_1.png` | 6 | oui | Focused and busy casting, sleeves pushed forward, determined straight mouth. The staff orb glows bright blue `#78C0F5`. |
| `wizard_thinking_1.png` | 8 | oui | Thoughtful, looking upward, mouth pulled to one side, three small glowing stars orbiting above the pointed hat. The staff orb glows cyan `#8FE0EC`. |
| `wizard_waiting_approval_1.png` | 6 | oui | Holding out an open parchment scroll toward the viewer with both hands, eyebrows raised, small round open mouth, politely waiting for an answer. The staff orb glows bright amber `#FFC85C`. |
| `wizard_success_1.png` | 6 | **non** | Delighted, big open happy grin, eyes squinting with joy, small sparkles around him, one arm raised in celebration. The staff orb glows green `#74E3A8`. |
| `wizard_confused_1.png` | 4 | oui | Puzzled, head tilted, one eyebrow up, small open mouth, a glowing question mark floating beside the hat. The staff orb glows red `#F0685A`. |
| `wizard_sleeping_1.png` | 4 | oui | Fast asleep standing up, eyes closed as two curved lines, tiny mouth, hat drooping forward over his face, floating "z" letters. The staff orb is dim `#5A5F86`. |
| `wizard_greeting_1.png` | 8 | **non** | Waving hello with his free hand raised high, warm open smile, welcoming. The staff orb glows warm gold `#F2C14E`. |
| `wizard_listening_1.png` | 6 | oui | Listening intently, one hand cupped behind his ear, leaning in slightly, attentive, small sound-wave arcs near that ear. The staff orb glows teal `#6FE3CE`. |
| `wizard_speaking_1.png` | 6 | oui | Talking, mouth open mid-word, one hand raised in a small explaining gesture. The staff orb glows light blue `#9AD7F7`. |
| `wizard_pointing_1.png` | 4 | oui | Pointing his staff decisively to the side, arm extended, looking in that direction, helpful and alert. The staff orb glows warm gold `#FFD97A`. |

### Optionnel : `assets/character/wizard.json`

Uniquement si les réglages par défaut (12 images/seconde, boucle sauf
`greeting` et `success`) ne vous vont pas :

```json
{
  "fps": 12,
  "thinking": { "fps": 16 },
  "greeting": { "loop": false }
}
```

Un fichier invalide est ignoré, jamais fatal.

---

## Conseils pratiques

- **Générez `idle` en premier et validez-le.** C'est lui qui définit le
  personnage ; toutes les autres poses doivent lui ressembler. Une fois qu'il
  vous plaît, utilisez-le comme image de référence dans le générateur si
  celui-ci le permet.
- **Vérifiez à 48 px** avant d'en générer quatorze. C'est là que la plupart des
  illustrations échouent : trop de détails, contraste insuffisant entre le
  visage et le chapeau.
- **Découpez le fond** si le générateur rend un fond opaque. Un fond blanc
  donnera un carré blanc autour du personnage à l'écran.
- L'icône de l'application se régénère à part, depuis le dessin par code :
  `.venv\Scripts\python.exe tools\make_icon.py`.

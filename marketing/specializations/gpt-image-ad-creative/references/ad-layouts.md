# Ad layout decisions

Read this before generating the final image or several placement variants.

## Match composition to placement

| Placement | Composition decision |
| --- | --- |
| Feed image | Make the product recognisable at a small size; keep the focal object and reserved copy space inside a comfortable central composition. |
| Vertical Story / Reel cover | Design vertically from the first prompt; do not crop a landscape banner into a portrait placement. Keep key objects clear of platform UI areas once the platform is known. |
| Product landing hero | Use a wider frame with deliberate negative space beside the subject for approved page copy. |
| Retargeting creative | Show the specific product, variation, or tangible proof that the viewer already encountered; avoid a generic gaming scene. |

## Copy-on-image rule

The generated visual should carry the mood and product evidence. Typeset price, date, code, required disclosure, and the main CTA outside the image-generation step whenever feasible. This avoids unreadable or outdated raster text and permits one visual to be adapted across markets.

## Useful prompt skeleton

```text
Use case: ads-marketing
Asset type: [placement]
Primary request: original product advertisement for [confirmed item]
Subject: [product and only verified properties]
Scene/backdrop: [original setting, not game key art]
Composition/framing: [orientation, focal object, reserved negative space]
Lighting/mood: [mood that fits the approved brand voice]
Text: no text in image
Constraints: preserve [product details]; no logos, no official-affiliation cues,
no watermark, no invented game UI, no unsupported price or claim
```

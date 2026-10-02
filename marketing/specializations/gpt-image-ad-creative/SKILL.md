---
name: gpt-image-ad-creative
description: "Create or edit original product-ad visuals for Hearthstone or Warcraft audiences using the built-in ImageGen workflow or, when explicitly requested, GPT Image 2 API/CLI. Use for banners, product mockups, social ads, image concepts, and visual variants; do not use for logo copying, unlicensed game art, or publishing an ad."
---

# GPT Image Ad Creative

Create an original, product-first advertising image with a clear visual job: stop the scroll, show the item, and leave a truthful message path to the offer.

## Brief before generation

Read [`../../brand-context.md`](../../brand-context.md), `../../../.agents/product-marketing.md` when it exists, and the current product brief. Confirm the item, target audience, platform/placement, landing page, visual assets and their rights, required message, and forbidden elements.

If an input image is supplied, label it as a reference, edit target, or supporting asset. Preserve a real product's identifiable details unless the user asks for a conceptual illustration. For Blizzard-related materials, follow [`../warcraft-product-advertising/references/claim-and-brand-safety.md`](../warcraft-product-advertising/references/claim-and-brand-safety.md).

Read [ad-layouts.md](references/ad-layouts.md) when choosing a composition or preparing multiple sizes.

## Generate deliberately

Use the built-in `$imagegen` workflow by default. It needs no API key. Use the model-specific GPT Image 2 CLI/API path only if the user explicitly asks for API, CLI, or `gpt-image-2`; follow the current [official GPT Image 2 documentation](https://developers.openai.com/api/docs/models/gpt-image-2) then.

Write a compact production prompt with: intended placement, real product subject, scene, composition, lighting, visual style, empty space for approved copy, and constraints. Use the `ads-marketing` or `product-mockup` taxonomy of `$imagegen` as appropriate.

- Generate distinct concepts, not superficial rewordings: for example product proof, use-in-context, gift, or collector appeal, but only when each angle is supported by the brief.
- Do not ask the model to fabricate customer results, price cards, discount codes, game UI, licensed logos, endorsements, or official game art.
- Keep essential price, legal text, and CTA out of the generated raster whenever possible. Reserve space so verified text can be typeset later. If text is intentionally rendered, quote it verbatim and visually inspect every character.
- For project-bound assets, keep the selected image in the workspace rather than only in the ImageGen default output location. Do not overwrite an earlier approved asset without a request.

## Hand off

Return the final prompt, chosen concept, intended placement, input-image roles, and a short fact/rights checklist. For any candidate selected for use, invoke `$ad-visual-review` with the visual and brief before presenting it as launch-ready.

"""Normalised dump of a replay as python-hsreplay / python-hslog see it.

Usage: python scripts/differential/dump-reference.py <replay.xml> > reference.json
Requires: pip install hsreplay hearthstone "setuptools<80"
"""
import json
import sys
import warnings

warnings.filterwarnings("ignore")

from hslog import packets  # noqa: E402
from hslog.export import EntityTreeExporter  # noqa: E402
from hsreplay.document import HSReplayDocument  # noqa: E402


def ref(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return str(value)


def normalise(packet):
    name = type(packet).__name__
    if isinstance(packet, packets.CreateGame):
        return [{"type": "CreateGame", "entity": packet.entity}] + [
            {"type": "Player", "entity": p.entity, "playerId": p.player_id} for p in packet.players
        ]
    if name == "Player":
        return [{"type": "Player", "entity": packet.entity, "playerId": packet.player_id}]
    if isinstance(packet, packets.FullEntity):
        return [{"type": "FullEntity", "entity": packet.entity, "cardId": packet.card_id or None, "tags": len(packet.tags)}]
    if isinstance(packet, packets.ShowEntity):
        return [{"type": "ShowEntity", "entity": ref(packet.entity), "cardId": packet.card_id or None, "tags": len(packet.tags)}]
    if isinstance(packet, packets.ChangeEntity):
        return [{"type": "ChangeEntity", "entity": ref(packet.entity), "cardId": packet.card_id or None, "tags": len(packet.tags)}]
    if isinstance(packet, packets.HideEntity):
        return [{"type": "HideEntity", "entity": ref(packet.entity), "zone": int(packet.zone)}]
    if isinstance(packet, packets.TagChange):
        return [{"type": "TagChange", "entity": ref(packet.entity), "tag": int(packet.tag), "value": int(packet.value)}]
    if isinstance(packet, packets.Block):
        head = {"type": "Block", "entity": ref(packet.entity), "blockType": int(packet.type), "target": ref(packet.target) or 0, "children": len(packet.packets)}
        out = [head]
        for child in packet.packets:
            out.extend(normalise(child))
        return out
    if isinstance(packet, packets.SubSpell):
        out = [{"type": "SubSpell", "entity": ref(packet.source), "children": len(packet.packets)}]
        for child in packet.packets:
            out.extend(normalise(child))
        return out
    if isinstance(packet, packets.MetaData):
        return [{"type": "MetaData", "meta": int(packet.meta), "data": int(packet.data), "info": len(packet.info)}]
    if isinstance(packet, packets.Choices):
        return [{"type": "Choices", "id": packet.id, "entity": ref(packet.entity), "choiceType": int(packet.type), "choices": len(packet.choices)}]
    if isinstance(packet, packets.ChosenEntities):
        return [{"type": "ChosenEntities", "id": packet.id, "entity": ref(packet.entity), "choices": len(packet.choices)}]
    if isinstance(packet, packets.SendChoices):
        return [{"type": "SendChoices", "id": packet.id, "choiceType": int(packet.type), "choices": len(packet.choices)}]
    if isinstance(packet, packets.Options):
        return [{"type": "Options", "id": packet.id, "options": len(packet.options)}]
    if isinstance(packet, packets.SendOption):
        return [{"type": "SendOption", "option": packet.option, "target": ref(packet.target) or 0}]
    if isinstance(packet, packets.ShuffleDeck):
        return [{"type": "ShuffleDeck", "playerId": packet.player_id}]
    return [{"type": name}]


def main(path):
    with open(path, "rb") as f:
        document = HSReplayDocument.from_xml_file(f)
    games = []
    for tree in document.to_packet_tree():
        flat = []
        for packet in tree.packets:
            flat.extend(normalise(packet))
        game = EntityTreeExporter(tree).export().game
        entities = sorted(
            ({"id": e.id, "cardId": getattr(e, "card_id", None) or None, "tags": {str(int(k)): int(v) for k, v in e.tags.items()}} for e in game.entities),
            key=lambda e: e["id"],
        )
        players = [{"entityId": p.id, "playerId": p.player_id, "name": p.name} for p in game.players]
        result = {str(p.id): (int(p.tags.get(17)) if p.tags.get(17) is not None else None) for p in game.players}
        games.append({"id": None, "players": players, "entities": entities, "packets": flat, "result": result})
    json.dump({"games": games}, sys.stdout, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])

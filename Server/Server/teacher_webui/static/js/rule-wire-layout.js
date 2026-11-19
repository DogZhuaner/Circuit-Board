// Reserve a separate track only when two wires occupy overlapping intervals.
function reserveWireTrack(tracks, a, b) {
    const low = Math.min(a, b);
    const high = Math.max(a, b);
    let index = tracks.findIndex(track => track.every(span => high < span.low || low > span.high));
    if (index < 0) index = tracks.push([]) - 1;
    tracks[index].push({ low, high });
    return index;
}

const WIRE_TRACK_GAP = 12;
const WIRE_COLORS = ['#2856c5', '#8737a5', '#a75412', '#077881', '#b53556', '#485699'];

function wireColor(id) {
    return WIRE_COLORS[(id - 1) % WIRE_COLORS.length];
}

function planRuleWireTracks(regions, wires) {
    const contacts = new Map();
    regions.forEach((region, column) => region.contacts.forEach(contact => {
        contacts.set(contact.name, { column, row: contact.row });
    }));
    const vertical = regions.map(() => []);
    const horizontal = {};
    const routes = wires.map(wire => {
        const start = contacts.get(wire.start);
        const end = contacts.get(wire.end);
        const distance = Math.abs(start.column - end.column);
        const startRight = start.column < end.column;
        const endRight = end.column < start.column;
        const firstGap = start.column + Number(startRight);
        const lastGap = end.column + Number(endRight);
        const route = { wire, startRight, endRight, firstGap, lastGap };
        if (distance <= 1) {
            if (distance === 0 || start.row !== end.row) {
                route.firstTrack = reserveWireTrack(vertical[firstGap], start.row, end.row);
            }
        } else {
            route.crossRow = Math.min(start.row, end.row);
            const band = horizontal[route.crossRow] ??= [];
            route.crossTrack = reserveWireTrack(band, firstGap, lastGap);
            route.firstTrack = reserveWireTrack(vertical[firstGap], route.crossRow - 0.5, start.row);
            route.lastTrack = reserveWireTrack(vertical[lastGap], route.crossRow - 0.5, end.row);
        }
        return route;
    });
    // Split leads immediately outside a shared socket while keeping its center as the endpoint.
    const ports = new Map();
    function addLead(contact, right, route, offsetProperty) {
        const key = JSON.stringify([contact, right]);
        if (!ports.has(key)) ports.set(key, []);
        ports.get(key).push({ route, offsetProperty });
    }
    for (const route of routes) {
        addLead(route.wire.start, route.startRight, route, 'startOffset');
        addLead(route.wire.end, route.endRight, route, 'endOffset');
    }
    for (const leads of ports.values()) {
        const step = Math.min(8, 16 / Math.max(1, leads.length - 1));
        leads.forEach(({ route, offsetProperty }, i) => {
            route[offsetProperty] = (i - (leads.length - 1) / 2) * step;
        });
    }
    const gaps = vertical.map((tracks, i) => tracks.length
        ? 18 + (tracks.length - 1) * WIRE_TRACK_GAP
        : (i === 0 ? 0 : 12));
    const rowSpacing = {};
    for (const [row, tracks] of Object.entries(horizontal)) rowSpacing[row] = 8 + tracks.length * WIRE_TRACK_GAP;
    return { routes, gaps, rowSpacing };
}

function placeRuleWireLabels(routes, width) {
    const occupied = [];
    const segments = routes.flatMap(route => {
        route.segments = route.points.slice(1).map((b, i) => {
            const a = route.points[i];
            return {
                a, b, length: Math.abs(a.x - b.x) + Math.abs(a.y - b.y),
                left: Math.min(a.x, b.x) - 1, right: Math.max(a.x, b.x) + 1,
                top: Math.min(a.y, b.y) - 1, bottom: Math.max(a.y, b.y) + 1
            };
        }).filter(s => s.length > 0.1).sort((a, b) => b.length - a.length);
        return route.segments;
    });
    const intersects = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    for (const route of routes) {
        if (!route.score) continue;
        const labelWidth = 8 * String(route.score).length + 6;
        let best;
        // Try the middle of a long segment first, then alternate positions along it.
        for (const segment of route.segments) {
            for (const fraction of [0.5, 0.3, 0.7, 0.15, 0.85]) {
                const { a, b } = segment;
                const x = Math.max(labelWidth / 2 + 1, Math.min(width - labelWidth / 2 - 1, a.x + (b.x - a.x) * fraction));
                const y = a.y + (b.y - a.y) * fraction;
                const box = { left: x - labelWidth / 2 - 2, right: x + labelWidth / 2 + 2, top: y - 10, bottom: y + 10 };
                let cost = occupied.filter(rect => intersects(box, rect)).length * 100;
                for (const other of segments) {
                    if (other !== segment && intersects(box, other)) cost++;
                }
                if (!best || cost < best.cost) best = { x, y, box, cost, width: labelWidth };
                if (cost === 0) break;
            }
            if (best.cost === 0) break;
        }
        if (best) {
            occupied.push(best.box);
            route.label = best;
        }
    }
}

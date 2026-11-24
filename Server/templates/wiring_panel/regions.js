const RULE_CONTACT_REGIONS = {% include 'wiring_panel/contacts.json' %};

function buildRuleContactRegions() {
    const inverterContacts = new Set([
        'L1', 'L2', 'L3', 'U2', 'V2', 'W2',
        '5/DI0', '6/DI1', '7/DI2', '8/DI3',
        '16/DI14', '17/DI15', '28/GND/69DI COM1/34/DI COM2'
    ]);
    return RULE_CONTACT_REGIONS.map(region => {
        let lastGroup = '';
        let row = 1;
        const contacts = region.contacts.map(name => {
            const group = inverterContacts.has(name) ? 'INV' : name.split('-')[0];
            const groupTitle = group === lastGroup ? '' : group;
            lastGroup = group;
            if (groupTitle) row++;
            return { name, groupTitle, row: ++row };
        });
        return { ...region, contacts, rowCount: row };
    });
}

const RULE_CONTACT_REGIONS = [
    {
        name: 'region_001',
        title: '区域一',
        contacts: ['QS1-1','QS1-3','QS1-5','QS1-7','FU1-1','FU1-3','FU1-5','FU2-1','FU2-3','KT1-A1','KT1-1/L1','KT1-3/L2','KT1-5/L3','KT1-55/NC','KT1-67/NO','KT2-A1','KT2-1/L1','KT2-3/L2','KT2-5/L3','KT2-55/NC','KT2-67/NO','PLC-L','PLC-N','PLC-PE','PLC-L+','PLC-M','PLC-1M','PLC-I0.0','PLC-I0.1','PLC-I0.2','PLC-I0.3','PLC-I0.4','PLC-I0.5','PLC-I0.6','PLC-I0.7']
    },
    {
        name: 'region_002',
        title: '区域二',
        contacts: ['QS1-2','QS1-4','QS1-6','QS1-8','FU1-2','FU1-4','FU1-6','FU2-2','FU2-4','KT1-A2','KT1-2/T1','KT1-4/T2','KT1-6/T3','KT1-56/NC','KT1-68/NO','KT2-A2','KT2-2/T1','KT2-4/T2','KT2-6/T3','KT2-56/NC','KT2-68/NO','PLC-1L','PLC-Q0.0','PLC-Q0.1','PLC-Q0.2','PLC-Q0.3','PLC-Q0.4','PLC-2L','PLC-Q0.5','PLC-Q0.6','PLC-Q0.7','L1','L2','L3','U2','V2','W2','5/DI0','6/DI1','7/DI2','8/DI3','16/DI14','17/DI15','28/GND/69DI COM1/34/DI COM2']
    },
    {
        name: 'region_003',
        title: '区域三',
        contacts: ['KM1-A1','KM1-1/L1','KM1-3/L2','KM1-5/L3','KM1-13/NO','KM1-53/NO','KM1-61/NC','KM1-71/NC','KM1-83/NO','KM2-A1','KM2-1/L1','KM2-3/L2','KM2-5/L3','KM2-13/NO','KM2-53/NO','KM2-61/NC','KM2-71/NC','KM2-83/NO','KM3-A1','KM3-1/L1','KM3-3/L2','KM3-5/L3','KM3-13/NO','KM3-53/NO','KM3-61/NC','KM3-71/NC','KM3-83/NO','FR1-1/L1','FR1-3/L2','FR1-5/L3','FR2-1/L1','FR2-3/L2','FR2-5/L3','SB1-1/NC','SB1-2/NC','SB1-3/NO','SB1-4/NO','SB2-1/NC','SB2-2/NC','SB2-3/NO','SB2-4/NO','SB3-1/NC','SB3-2/NC','SB3-3/NO','SB3-4/NO','HL1-1','HL1-2','HL2-1','HL2-2','HL3-1','HL3-2']
    },
    {
        name: 'region_004',
        title: '区域四',
        contacts: ['KM1-A2','KM1-2/T1','KM1-4/T2','KM1-6/T3','KM1-14/NO','KM1-54/NO','KM1-62/NC','KM1-72/NC','KM1-84/NO','KM2-A2','KM2-2/T1','KM2-4/T2','KM2-6/T3','KM2-14/NO','KM2-54/NO','KM2-62/NC','KM2-72/NC','KM2-84/NO','KM3-A2','KM3-2/T1','KM3-4/T2','KM3-6/T3','KM3-14/NO','KM3-54/NO','KM3-62/NC','KM3-72/NC','KM3-84/NO','FR1-2/T1','FR1-4/T2','FR1-6/T3','FR1-98/NO','FR1-97/NO','FR1-96/NC','FR1-95/NC','FR2-2/T1','FR2-4/T2','FR2-6/T3','FR2-98/NO','FR2-97/NO','FR2-96/NC','FR2-95/NC','XT1-1','XT1-2','XT1-3','XT1-4','XT1-5','XT1-6','XT2-1','XT2-2','XT2-3','XT2-4','XT2-5','XT2-6']
    }
];

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

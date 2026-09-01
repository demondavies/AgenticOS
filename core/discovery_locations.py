"""Unattended discovery queue — seed list of UK towns to cycle through.

UK_TOWNS covers England, Scotland, and Wales: market towns and urban centres
with enough independent business density to plausibly have their own
accountancy practices. Real town/county names throughout.
"""
from __future__ import annotations

from core.db import get_db

UK_TOWNS: list[dict] = []


def _add(region: str, county: str, towns: list[str]) -> None:
    for town in towns:
        UK_TOWNS.append({"town": town, "county": county, "region": region})


# ---------------------------------------------------------------------------
# South West
# ---------------------------------------------------------------------------
_add("South West", "Devon", [
    "Exeter", "Plymouth", "Torquay", "Barnstaple", "Bideford", "Ilfracombe",
    "South Molton", "Crediton", "Okehampton", "Tavistock", "Totnes",
    "Newton Abbot", "Paignton", "Brixham", "Dawlish", "Teignmouth",
    "Sidmouth", "Exmouth", "Axminster", "Honiton", "Cullompton", "Tiverton",
])
_add("South West", "Bristol", ["Bristol"])
_add("South West", "Somerset", [
    "Bath", "Taunton", "Yeovil", "Minehead", "Bridgwater", "Wells", "Frome",
    "Shepton Mallet", "Glastonbury", "Street", "Chard", "Ilminster",
    "Crewkerne", "Wincanton",
])
_add("South West", "Cornwall", [
    "Truro", "Newquay", "Falmouth", "Penzance", "St Austell", "Bodmin",
    "Launceston",
])
_add("South West", "Wiltshire", ["Salisbury", "Swindon"])
_add("South West", "Gloucestershire", [
    "Cheltenham", "Gloucester", "Cirencester", "Stroud",
])
_add("South West", "Dorset", [
    "Sherborne", "Dorchester", "Weymouth", "Blandford Forum", "Shaftesbury",
    "Wimborne", "Poole", "Bournemouth", "Christchurch",
])
_add("South West", "Hampshire", ["Ringwood", "Lymington", "Romsey"])

# ---------------------------------------------------------------------------
# South East
# ---------------------------------------------------------------------------
_add("South East", "Greater London", [
    "Westminster", "Camden", "Islington", "Hackney", "Southwark", "Lambeth",
    "Greenwich", "Wandsworth", "Croydon", "Barnet",
])
_add("South East", "East Sussex", [
    "Brighton", "Hastings", "Eastbourne", "Lewes", "Bexhill",
])
_add("South East", "Hampshire", [
    "Southampton", "Portsmouth", "Winchester", "Basingstoke", "Andover",
    "Alton",
])
_add("South East", "Oxfordshire", ["Oxford"])
_add("South East", "Berkshire", ["Reading"])
_add("South East", "Surrey", [
    "Guildford", "Farnham", "Woking", "Reigate",
])
_add("South East", "Kent", [
    "Maidstone", "Canterbury", "Tunbridge Wells", "Folkestone", "Dover",
    "Deal", "Sandwich", "Faversham", "Sittingbourne", "Gillingham",
    "Rochester", "Gravesend", "Sevenoaks", "Tonbridge", "Tenterden",
])
_add("South East", "West Sussex", [
    "Worthing", "Chichester", "Crawley", "Horsham", "Haywards Heath",
])

# ---------------------------------------------------------------------------
# Midlands
# ---------------------------------------------------------------------------
_add("Midlands", "West Midlands", ["Birmingham", "Coventry", "Wolverhampton"])
_add("Midlands", "Leicestershire", ["Leicester"])
_add("Midlands", "Nottinghamshire", ["Nottingham"])
_add("Midlands", "Derbyshire", ["Derby"])
_add("Midlands", "Staffordshire", [
    "Stoke-on-Trent", "Tamworth", "Lichfield", "Burton upon Trent", "Stafford",
])
_add("Midlands", "Shropshire", [
    "Shrewsbury", "Telford", "Ludlow", "Bridgnorth",
])
_add("Midlands", "Worcestershire", [
    "Worcester", "Kidderminster", "Redditch", "Evesham", "Malvern",
])
_add("Midlands", "Herefordshire", [
    "Hereford", "Ross-on-Wye", "Ledbury", "Leominster",
])
_add("Midlands", "Warwickshire", [
    "Stratford-upon-Avon", "Warwick", "Leamington Spa", "Rugby", "Nuneaton",
])

# ---------------------------------------------------------------------------
# North
# ---------------------------------------------------------------------------
_add("North", "Greater Manchester", [
    "Manchester", "Wigan", "Bolton", "Bury", "Rochdale", "Oldham",
    "Stockport", "Sale", "Altrincham",
])
_add("North", "Merseyside", ["Liverpool"])
_add("North", "West Yorkshire", [
    "Leeds", "Bradford", "Wakefield", "Huddersfield", "Halifax", "Keighley",
    "Ilkley", "Otley", "Wetherby",
])
_add("North", "South Yorkshire", [
    "Sheffield", "Doncaster", "Rotherham", "Barnsley",
])
_add("North", "East Riding of Yorkshire", [
    "Hull", "Bridlington", "Beverley", "Goole",
])
_add("North", "North Yorkshire", [
    "York", "Middlesbrough", "Harrogate", "Skipton", "Ripon",
    "Northallerton", "Thirsk", "Scarborough", "Whitby", "Selby",
])
_add("North", "Tyne and Wear", ["Newcastle", "Sunderland"])
_add("North", "Lincolnshire", [
    "Grimsby", "Scunthorpe", "Lincoln", "Boston", "Grantham", "Stamford",
    "Louth", "Horncastle", "Spalding", "Bourne", "Sleaford",
])
_add("North", "Nottinghamshire", ["Retford", "Worksop", "Mansfield"])
_add("North", "Derbyshire", ["Matlock", "Bakewell", "Buxton", "Glossop"])
_add("North", "Cheshire", [
    "Macclesfield", "Congleton", "Crewe", "Nantwich", "Chester",
    "Northwich", "Winsford", "Runcorn", "Warrington", "Wilmslow",
    "Knutsford", "Alderley Edge",
])
_add("North", "Lancashire", [
    "Preston", "Blackpool", "Blackburn", "Burnley", "Accrington",
    "Clitheroe", "Lancaster", "Morecambe",
])
_add("North", "Cumbria", [
    "Kendal", "Ulverston", "Barrow-in-Furness", "Windermere", "Keswick",
    "Penrith", "Carlisle", "Workington", "Whitehaven", "Cockermouth",
])

# ---------------------------------------------------------------------------
# East
# ---------------------------------------------------------------------------
_add("East", "Cambridgeshire", [
    "Cambridge", "Peterborough", "Ely", "March", "Wisbech", "St Neots",
    "Huntingdon", "Ramsey",
])
_add("East", "Norfolk", [
    "Norwich", "King's Lynn", "Fakenham", "Dereham", "Wymondham",
    "Attleborough", "Thetford", "Diss",
])
_add("East", "Suffolk", [
    "Ipswich", "Bury St Edmunds", "Newmarket", "Beccles", "Lowestoft",
    "Bungay", "Eye", "Stowmarket", "Needham Market", "Hadleigh", "Sudbury",
])
_add("East", "Essex", [
    "Colchester", "Chelmsford", "Southend-on-Sea", "Halstead", "Braintree",
    "Witham", "Maldon", "Brentwood", "Harlow",
])
_add("East", "Hertfordshire", [
    "Bishop's Stortford", "Hertford", "Ware", "Stevenage", "Hitchin",
    "Letchworth", "St Albans", "Watford", "Hemel Hempstead", "Berkhamsted",
    "Tring",
])
_add("East", "Bedfordshire", ["Luton", "Dunstable", "Bedford", "Sandy"])

# ---------------------------------------------------------------------------
# Wales
# ---------------------------------------------------------------------------
_add("Wales", "South Glamorgan", ["Cardiff"])
_add("Wales", "West Glamorgan", ["Swansea"])
_add("Wales", "Gwent", ["Newport", "Pontypool", "Abergavenny"])
_add("Wales", "Clwyd", ["Wrexham"])
_add("Wales", "Gwynedd", [
    "Bangor", "Dolgellau", "Barmouth", "Pwllheli", "Caernarfon",
])
_add("Wales", "Ceredigion", ["Aberystwyth", "Cardigan", "Lampeter"])
_add("Wales", "Carmarthenshire", ["Carmarthen", "Llanelli", "Llandovery"])
_add("Wales", "Mid Glamorgan", ["Merthyr Tydfil", "Bridgend"])
_add("Wales", "Powys", [
    "Brecon", "Llandrindod Wells", "Builth Wells", "Machynlleth",
])
_add("Wales", "Pembrokeshire", ["Haverfordwest", "Pembroke", "Tenby"])
_add("Wales", "Anglesey", ["Llangefni", "Holyhead"])
_add("Wales", "Conwy", ["Colwyn Bay"])
_add("Wales", "Denbighshire", ["Rhyl", "Prestatyn", "Denbigh", "Ruthin"])
_add("Wales", "Flintshire", ["Mold", "Flint"])

# ---------------------------------------------------------------------------
# Scotland
# ---------------------------------------------------------------------------
_add("Scotland", "Midlothian", ["Edinburgh"])
_add("Scotland", "Lanarkshire", ["Glasgow"])
_add("Scotland", "Aberdeenshire", [
    "Aberdeen", "Stonehaven", "Banchory", "Ballater", "Huntly", "Banff",
    "Fraserburgh", "Peterhead",
])
_add("Scotland", "Angus", [
    "Dundee", "Arbroath", "Montrose", "Brechin", "Forfar", "Kirriemuir",
])
_add("Scotland", "Highland", [
    "Inverness", "Fort William", "Portree", "Nairn", "Dingwall", "Tain",
    "Ullapool", "Gairloch",
])
_add("Scotland", "Stirlingshire", ["Stirling", "Falkirk"])
_add("Scotland", "Perthshire", [
    "Perth", "Pitlochry", "Aberfeldy", "Blairgowrie",
])
_add("Scotland", "Fife", ["St Andrews", "Dunfermline", "Kirkcaldy"])
_add("Scotland", "Renfrewshire", ["Paisley"])
_add("Scotland", "Ayrshire", ["Kilmarnock", "Ayr"])
_add("Scotland", "Dumfriesshire", ["Dumfries"])
_add("Scotland", "Scottish Borders", [
    "Galashiels", "Hawick", "Jedburgh", "Peebles", "Kelso", "Melrose",
])
_add("Scotland", "Northumberland", ["Berwick-upon-Tweed"])
_add("Scotland", "Argyll", ["Oban", "Tobermory"])
_add("Scotland", "Caithness", ["Thurso", "Wick"])
_add("Scotland", "Moray", ["Elgin", "Forres", "Keith", "Buckie"])


def seed_discovery_queue() -> int:
    """Bulk-insert every UK_TOWNS entry into discovery_queue. Safe to re-run."""
    conn = get_db()
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO discovery_queue (town, county, region) "
            "VALUES (:town, :county, :region)",
            UK_TOWNS,
        )
        conn.commit()
        return conn.total_changes
    finally:
        conn.close()

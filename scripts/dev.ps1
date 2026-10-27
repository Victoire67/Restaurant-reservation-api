# Developer shortcuts. Load into your terminal with:  . .\scripts\dev.ps1

function show {
    param(
        [Parameter(Mandatory)]
        [ValidateSet("cities", "restaurants", "tables", "customers", "reservations", "reviews")]
        [string]$What
    )

    $queries = @{
        cities       = "SELECT * FROM cities ORDER BY id;"
        restaurants  = "SELECT id, city_id, name, address, phone, ST_AsText(location) AS location FROM restaurants ORDER BY id;"
        tables       = "SELECT * FROM restaurant_tables ORDER BY id;"
        customers    = "SELECT * FROM customers ORDER BY id;"
        reservations = "SELECT * FROM reservations ORDER BY id;"
        reviews      = "SELECT * FROM reviews ORDER BY id;"
    }

    docker compose exec postgres psql -U restaurant -d restaurant_db -c $queries[$What]
}

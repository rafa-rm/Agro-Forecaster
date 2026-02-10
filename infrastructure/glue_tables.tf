resource "aws_glue_catalog_database" "agro_data_db" {
  name = "agro_data_db"
}

resource "aws_glue_catalog_table" "raw_tables" {
    for_each = var.commodities

    name          = each.key
    database_name = aws_glue_catalog_database.agro_data_db.name
    table_type = "EXTERNAL_TABLE"

    parameters = {
        "classification" = "parquet"

        "projection.enabled" = "true"

        "projection.year.type" = "integer"
        "projection.year.range" = "2010,2030"

        "projection.month.type" = "integer"
        "projection.month.range" = "1,12"

        "projection.day.type" = "integer"
        "projection.day.range" = "1,31"

        "storage.location.template" = "s3://${aws_s3_bucket.agro_data_lake.id}/raw/${each.key}/year=$${year}}/month=$${month}}/day=$${day}}/"
    }

    storage_descriptor {
        location      = "s3://${aws_s3_bucket.agro_data_lake.id}/raw/${each.key}/"
        input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
        output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
    
        ser_de_info {
            serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
            parameters = {
              "serialization.format" = "1"
            }
        }

        columns {
            name = "date"
            type = "string"
        }

        columns {
            name = "open" 
            type = "double"
        }

        columns {
            name = "high"
            type = "double" 
        }

        columns {
            name = "low"
            type = "double"  
        }

        columns {
            name = "close"
            type = "double"  
        }
    }

    partition_keys {
        name = "year"
        type = "int"
    }

    partition_keys {
        name = "month"
        type = "int"
    }

    partition_keys {
        name = "day"
        type = "int" 
    }
  
}
resource "aws_s3_bucket" "agro_data_lake" {
  bucket = var.agro_bucket_name

  tags = {
    Environment = var.environment
    Name        = "Agro Data Lake"
  }
}

resource "aws_s3_bucket_versioning" "agro_data_lake_versioning" {
  bucket = aws_s3_bucket.agro_data_lake.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "agro_data_lake_lifecycle" {
  bucket = aws_s3_bucket.agro_data_lake.id

  rule {
    id     = "Delete old versions"
    status = "Enabled"

    expiration {
      # Permanently delete objects 30 days after their creation date
      days = 30
    }
  }
}

resource "aws_s3_bucket" "lambda_code_bucket" {
  bucket = "${var.agro_bucket_name}-lambda-code"

  tags = {
    Environment = var.environment
    Name        = "Agro Lambda Code Bucket"
  }
}

data "archive_file" "lambda_code" {
  type        = "zip"
  source_file = "../src/get_yf_data.py"  
  output_path = "${path.module}/get_yf_data.zip"
}

resource "aws_s3_object" "layer_zip" {
  bucket = aws_s3_bucket.lambda_code_bucket.id   
  key    = "layers/agro_forecaster_layer.zip"
  source = "../src/agro_forecaster_layer.zip"
  etag   = filemd5("../src/agro_forecaster_layer.zip")
}

resource "aws_s3_object" "code_get_yf_data_zip" {
  bucket = aws_s3_bucket.lambda_code_bucket.id
  key    = "code/get_yf_data.zip"
  source = data.archive_file.lambda_code.output_path
  etag   = data.archive_file.lambda_code.output_base64sha256
}


resource "aws_scheduler_schedule" "agro_scraper_schedule" {
  name        = "agro-scraper-schedule"
  description = "Schedule for Agro Scraper Lambda"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = "cron(0 23 * * ? *)"

  target {
    arn      = aws_lambda_function.agro_scraper.arn
    role_arn = aws_iam_role.scheduler_role.arn
  }
}

resource "aws_lambda_layer_version" "agro_layer" {
  layer_name          = "agro-dependencies"
  description         = "Pandas, Requests, OpenPyxl, Xlrd"
  compatible_runtimes = ["python3.14"]

  s3_bucket = aws_s3_bucket.lambda_code_bucket.id
  s3_key    = aws_s3_object.layer_zip.key
  source_code_hash = filebase64sha256("../src/agro_forecaster_layer.zip")
}

resource "aws_lambda_function" "agro_scraper" {
  function_name = "agro-data-ingestion"
  description   = "Daily ingestion of CEPEA Soy/Corn prices"
  role          = aws_iam_role.lambda_exec_role.arn
  handler       = "get_yf_data.lambda_handler" 
  runtime       = "python3.14"
  timeout       = 600 
  memory_size   = 1024 

  s3_bucket = aws_s3_bucket.lambda_code_bucket.id
  s3_key    = aws_s3_object.code_get_yf_data_zip.key
  source_code_hash = data.archive_file.lambda_code.output_base64sha256

  # Attach the Layer
  layers = [aws_lambda_layer_version.agro_layer.arn]

  # Environment Variables
  environment {
    variables = {
      S3_BUCKET_NAME = aws_s3_bucket.agro_data_lake.id
    }
  }
}

resource "aws_glue_catalog_database" "agro_data_db" {
  name = "agro_data_db"
}

resource "aws_glue_crawler" "agro_data_crawler" {
  name         = "agro-data-crawler"
  database_name = aws_glue_catalog_database.agro_data_db.name
  role         = aws_iam_role.glue_service_role.arn

  s3_target {
    path = "s3://${aws_s3_bucket.agro_data_lake.id}/raw/soybean/"
  }

  s3_target {
    path = "s3://${aws_s3_bucket.agro_data_lake.id}/raw/corn/"
  }

  s3_target {
    path = "s3://${aws_s3_bucket.agro_data_lake.id}/raw/usd_brl/"
  }

  s3_target {
    path = "s3://${aws_s3_bucket.agro_data_lake.id}/raw/wheat/"
  }

  s3_target {
    path = "s3://${aws_s3_bucket.agro_data_lake.id}/raw/oil/"
  }

  recrawl_policy {
    recrawl_behavior = "CRAWL_NEW_FOLDERS_ONLY"
  }

  schema_change_policy {
    delete_behavior = "LOG"
    update_behavior = "LOG" 
  }

}

resource "aws_glue_trigger" "daily_crawl" {
  name     = "daily-agro-crawl"
  schedule = "cron(0 8 * * ? *)" 
  type     = "SCHEDULED"

  actions {
    job_name = aws_glue_crawler.agro_data_crawler.name
  }
}

resource "aws_s3_bucket" "athena_results" {
  bucket = "${var.agro_bucket_name}-athena-results"

  tags = {
    Environment = var.environment
  }
}

resource "aws_athena_workgroup" "agro_workgroup" {
  name = "agro-analytics"

  configuration {
    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.bucket}/output/"
    }

    enforce_workgroup_configuration = true
  }
}
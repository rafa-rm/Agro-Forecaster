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

resource "aws_s3_bucket" "lambda_code_bucket" {
  bucket = "${var.agro_bucket_name}-lambda-code"

  tags = {
    Environment = var.environment
    Name        = "Agro Lambda Code Bucket"
  }
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

resource "aws_s3_object" "code_process_yf_data_zip" {
  bucket = aws_s3_bucket.lambda_code_bucket.id
  key    = "code/process_yf_data.zip"
  source = data.archive_file.lambda_code_process_yf_data.output_path
  etag   = data.archive_file.lambda_code_process_yf_data.output_base64sha256
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
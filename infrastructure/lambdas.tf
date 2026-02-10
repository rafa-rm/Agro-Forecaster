data "archive_file" "lambda_code" {
  type        = "zip"
  source_file = "../src/get_yf_data.py"  
  output_path = "${path.module}/get_yf_data.zip"
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

  layers = [aws_lambda_layer_version.agro_layer.arn]

  environment {
    variables = {
      S3_BUCKET_NAME = aws_s3_bucket.agro_data_lake.id
    }
  }
}
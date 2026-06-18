data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "raw_role" {
  name               = "agro-raw-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role" "trusted_role" {
  name               = "agro-trusted-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role" "enriched_role" {
  name               = "agro-enriched-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role" "predictor_role" {
  name               = "agro-predictor-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}


resource "aws_iam_role_policy" "raw_permissions" {
  name = "raw-permissions"
  role = aws_iam_role.raw_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow", 
        Action = ["s3:PutObject"],
        Resource = ["${aws_s3_bucket.agro_data_lake.arn}/raw/*"] 
      },
      {
         Effect = "Allow",
         Action = ["s3:ListBucket"], 
         Resource = [aws_s3_bucket.agro_data_lake.arn]
      },
      {
        Effect = "Allow", Action = "lambda:InvokeFunction",
        Resource = aws_lambda_function.agro_processor.arn 
      },
      {
        Effect = "Allow", 
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "trusted_permissions" {
  name = "trusted-permissions"
  role = aws_iam_role.trusted_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow", 
        Action = ["s3:GetObject"],
        Resource = ["${aws_s3_bucket.agro_data_lake.arn}/raw/*"] 
      },
      {
        Effect = "Allow", 
        Action = ["s3:GetObject"],
        Resource = ["${aws_s3_bucket.agro_data_lake.arn}/trusted/*"] 
      },
      {
        Effect = "Allow", 
        Action = ["s3:ListBucket"],
        Resource = [aws_s3_bucket.agro_data_lake.arn]
      },
      {
        Effect = "Allow", Action = ["s3:PutObject"],
        Resource = ["${aws_s3_bucket.agro_data_lake.arn}/trusted/*"] 
      },
      {
        Effect = "Allow", Action = "lambda:InvokeFunction",
        Resource = [
          aws_lambda_function.agro_enricher.arn,
          aws_lambda_function.agro_predictor.arn
        ]
      },
      {
        Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "enriched_permissions" {
  name = "enriched-permissions"
  role = aws_iam_role.enriched_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow", Action = ["s3:GetObject"],
        Resource = ["${aws_s3_bucket.agro_data_lake.arn}/trusted/*"]
      },
      {
        Effect = "Allow", Action = ["s3:PutObject"],
        Resource = ["${aws_s3_bucket.agro_data_lake.arn}/enriched/*"]
      },
      {
        Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "predictor_permissions" {
  name = "predictor-permissions"
  role = aws_iam_role.predictor_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject"]
        Resource = [
          "${aws_s3_bucket.agro_data_lake.arn}/trusted/*",
          "${aws_s3_bucket.agro_data_lake.arn}/saved_scalers/*",
          "${aws_s3_bucket.agro_data_lake.arn}/deployable_models/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = ["${aws_s3_bucket.agro_data_lake.arn}/forecasts/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.agro_data_lake.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role" "scheduler_role" {
  name = "agro-scheduler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_start_policy" {
  name = "start-pipeline"
  role = aws_iam_role.scheduler_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.agro_scraper.arn 
    }]
  })
}